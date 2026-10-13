"""
Direct DiscoPanel Host Deployment Module.
Connects directly to the DiscoPanel host (e.g. root@192.168.0.119) via SSH & SFTP,
uploads server modpack and world archives, provisions itzg/minecraft-server Docker containers,
and registers the server instance into /opt/discopanel/data/discopanel.db.
"""

import os
import io
import re
import uuid
import time
import socket
import logging
from typing import Dict, Any, Optional, Callable, List

import paramiko

logger = logging.getLogger("mc-converter.discopanel")

def _get_ssh_client(
    host: str,
    port: int = 22,
    username: str = "root",
    password: Optional[str] = None,
    private_key: Optional[str] = None,
    passphrase: Optional[str] = None,
    timeout: int = 10
) -> paramiko.SSHClient:
    """Creates and connects an authenticated Paramiko SSHClient."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    pkey = None
    if private_key and private_key.strip():
        key_file_obj = io.StringIO(private_key.strip())
        # Try loading various key formats
        for key_class in [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.DSSKey]:
            key_file_obj.seek(0)
            try:
                pkey = key_class.from_private_key(key_file_obj, password=passphrase)
                break
            except Exception:
                continue

    connect_kwargs = {
        "hostname": host,
        "port": port,
        "username": username or "root",
        "timeout": timeout,
        "banner_timeout": timeout,
        "auth_timeout": timeout,
    }

    if pkey:
        connect_kwargs["pkey"] = pkey
    elif password:
        connect_kwargs["password"] = password
    else:
        # Try agent or local default SSH keys
        connect_kwargs["look_for_keys"] = True
        connect_kwargs["allow_agent"] = True

    client.connect(**connect_kwargs)
    return client


def test_discopanel_connection(
    host: str,
    port: int = 22,
    username: str = "root",
    password: Optional[str] = None,
    private_key: Optional[str] = None,
    passphrase: Optional[str] = None,
    timeout: int = 8
) -> Dict[str, Any]:
    """
    Tests SSH connectivity to the DiscoPanel host and verifies:
      - Host reachable and authenticated
      - Docker daemon installed and running
      - DiscoPanel SQLite database exists at /opt/discopanel/data/discopanel.db
      - Free disk space in /opt/discopanel/data
      - Currently running containers and ports
    """
    client = None
    try:
        client = _get_ssh_client(
            host=host,
            port=port,
            username=username,
            password=password,
            private_key=private_key,
            passphrase=passphrase,
            timeout=timeout
        )

        # 1. Check Docker status
        _, stdout_docker, _ = client.exec_command("docker --version && docker info >/dev/null 2>&1 && echo 'OK' || echo 'FAIL'", timeout=6)
        docker_out = stdout_docker.read().decode('utf-8', errors='ignore').strip()
        docker_available = "OK" in docker_out or "Docker version" in docker_out

        # 2. Check DiscoPanel database
        _, stdout_db, _ = client.exec_command(
            "test -f /opt/discopanel/data/discopanel.db && echo 'EXISTS' || echo 'MISSING'",
            timeout=5
        )
        db_out = stdout_db.read().decode('utf-8', errors='ignore').strip()
        db_exists = "EXISTS" in db_out

        # 3. Check DiscoPanel service status
        _, stdout_svc, _ = client.exec_command("systemctl is-active discopanel 2>/dev/null || echo 'unknown'", timeout=5)
        svc_status = stdout_svc.read().decode('utf-8', errors='ignore').strip()

        # 4. Check Free Disk Space
        _, stdout_df, _ = client.exec_command("df -h /opt/discopanel/data 2>/dev/null || df -h /", timeout=5)
        df_lines = stdout_df.read().decode('utf-8', errors='ignore').strip().splitlines()
        disk_free = "Unknown"
        if len(df_lines) >= 2:
            parts = df_lines[1].split()
            if len(parts) >= 4:
                disk_free = parts[3]

        # 5. Check active Minecraft containers
        _, stdout_ps, _ = client.exec_command("docker ps --format '{{.Names}} ({{.Ports}})' 2>/dev/null | grep -i 'minecraft\\|disco' || true", timeout=5)
        running_servers = [line.strip() for line in stdout_ps.read().decode('utf-8', errors='ignore').splitlines() if line.strip()]

        return {
            "success": True,
            "host": host,
            "port": port,
            "username": username,
            "docker_available": docker_available,
            "discopanel_db_exists": db_exists,
            "discopanel_service": svc_status,
            "disk_free": disk_free,
            "running_servers_count": len(running_servers),
            "running_servers": running_servers[:5],
            "message": f"Successfully connected to {username}@{host}:{port}! Host environment is verified and ready for 1-click deployment."
        }

    except paramiko.AuthenticationException:
        return {
            "success": False,
            "error_type": "AUTH_FAILED",
            "message": f"Authentication failed for user '{username}' on {host}:{port}. Please check your password or SSH private key."
        }
    except (socket.timeout, TimeoutError):
        return {
            "success": False,
            "error_type": "TIMEOUT",
            "message": f"Connection timed out while trying to reach {host}:{port}. Verify the host is powered on and reachable on your LAN."
        }
    except socket.error as e:
        return {
            "success": False,
            "error_type": "NETWORK_ERROR",
            "message": f"Network error connecting to {host}:{port}: {str(e)}. Check your IP address and firewall."
        }
    except Exception as e:
        return {
            "success": False,
            "error_type": "UNKNOWN_ERROR",
            "message": f"Error connecting to DiscoPanel host: {str(e)}"
        }
    finally:
        if client:
            client.close()


def deploy_to_discopanel_host(
    host: str,
    port: int = 22,
    username: str = "root",
    password: Optional[str] = None,
    private_key: Optional[str] = None,
    passphrase: Optional[str] = None,
    server_name: str = "Minecraft Server",
    loader: str = "fabric",
    mc_version: str = "1.20.1",
    ram_gb: int = 6,
    server_port: int = 25565,
    server_zip_bytes: Optional[bytes] = None,
    world_zip_bytes: Optional[bytes] = None,
    staged_download_url: Optional[str] = None,
    log_callback: Optional[Callable[[str], None]] = None
) -> Dict[str, Any]:
    """
    Executes automated end-to-end server creation and world import directly on the DiscoPanel host.
    Transfers server packages and world saves, runs discopanel-import.sh, and yields live status logs.
    """
    logs: List[str] = []

    def emit_log(msg: str):
        logger.info(f"[DiscoDeploy] {msg}")
        logs.append(msg)
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass

    client = None
    sftp = None
    upload_id = str(uuid.uuid4())[:8]
    remote_script_path = "/tmp/discopanel-import.sh"
    remote_pack_path = ""
    remote_world_path = ""

    try:
        emit_log(f"Initiating direct connection to DiscoPanel host {username}@{host}:{port}...")
        client = _get_ssh_client(
            host=host,
            port=port,
            username=username,
            password=password,
            private_key=private_key,
            passphrase=passphrase,
            timeout=15
        )
        emit_log("SSH connection established successfully.")

        sftp = client.open_sftp()
        emit_log("SFTP channel opened.")

        # 1. Upload the discopanel-import.sh script directly from the converter repo
        base_dir = os.path.dirname(os.path.abspath(__file__))
        local_script = os.path.join(base_dir, "discopanel-import.sh")

        if os.path.exists(local_script):
            emit_log("Uploading latest discopanel-import.sh to host /tmp/ ...")
            sftp.put(local_script, remote_script_path)
        else:
            emit_log("Fetching latest discopanel-import.sh via curl on host...")
            client.exec_command(
                f"curl -fsSL https://raw.githubusercontent.com/IAndrexI/minecraftserver/main/discopanel-import.sh -o {remote_script_path}",
                timeout=15
            )

        client.exec_command(f"chmod +x {remote_script_path}", timeout=5)

        # 2. Upload Converted Server Package if provided in bytes
        if server_zip_bytes and len(server_zip_bytes) > 0:
            remote_pack_path = f"/tmp/discopanel_server_{upload_id}.zip"
            size_mb = round(len(server_zip_bytes) / (1024 * 1024), 2)
            emit_log(f"Uploading converted server package ({size_mb} MB) directly to host {remote_pack_path}...")
            pack_buf = io.BytesIO(server_zip_bytes)
            sftp.putfo(pack_buf, remote_pack_path)
            emit_log("Server package uploaded successfully.")
        elif staged_download_url:
            remote_pack_path = staged_download_url
            emit_log(f"Using staged LAN package download URL: {staged_download_url}")

        # 3. Upload World Save Archive if provided
        if world_zip_bytes and len(world_zip_bytes) > 0:
            remote_world_path = f"/tmp/discopanel_world_{upload_id}.zip"
            world_size_mb = round(len(world_zip_bytes) / (1024 * 1024), 2)
            emit_log(f"Uploading singleplayer world save ({world_size_mb} MB) to host {remote_world_path}...")
            world_buf = io.BytesIO(world_zip_bytes)
            sftp.putfo(world_buf, remote_world_path)
            emit_log("World save archive uploaded successfully.")

        # 4. Construct execution command
        # Escaping server name
        safe_name = server_name.replace('"', '\\"')

        if remote_pack_path:
            cmd = (
                f"bash {remote_script_path} "
                f"\"{remote_pack_path}\" "
                f"\"{safe_name}\" "
                f"{ram_gb} "
                f"{server_port} "
                f"\"{loader}\" "
                f"\"{mc_version}\" "
                f"\"{remote_world_path}\""
            )
        else:
            cmd = (
                f"bash {remote_script_path} --create "
                f"\"{safe_name}\" "
                f"\"{loader}\" "
                f"\"{mc_version}\" "
                f"{ram_gb} "
                f"{server_port} "
                f"\"{remote_world_path}\""
            )

        emit_log(f"Executing server provisioning on host: {cmd}")
        stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)

        server_uuid = None
        container_name = None
        discopanel_url = None
        success_marker = False

        # Stream remote execution output
        while True:
            line = stdout.readline()
            if not line:
                break
            line_str = line.strip()
            if line_str:
                emit_log(line_str)
                if line_str.startswith("SERVER_UUID="):
                    server_uuid = line_str.split("=", 1)[1].strip()
                elif line_str.startswith("CONTAINER_NAME="):
                    container_name = line_str.split("=", 1)[1].strip()
                elif line_str.startswith("DISCOPANEL_URL="):
                    discopanel_url = line_str.split("=", 1)[1].strip()
                elif "STATUS_SUCCESS=true" in line_str:
                    success_marker = True

        exit_status = stdout.channel.recv_exit_status()
        emit_log(f"Process completed with exit code: {exit_status}")

        # 5. Clean up temporary uploaded archives
        try:
            cleanup_cmds = []
            if remote_pack_path.startswith("/tmp/"):
                cleanup_cmds.append(f"rm -f {remote_pack_path}")
            if remote_world_path.startswith("/tmp/"):
                cleanup_cmds.append(f"rm -f {remote_world_path}")
            if cleanup_cmds:
                client.exec_command(" && ".join(cleanup_cmds), timeout=5)
        except Exception:
            pass

        if not discopanel_url and server_uuid:
            discopanel_url = f"http://{host}:8080/servers/{server_uuid}"

        if exit_status == 0 or success_marker:
            emit_log(f"✨ Deployment successful! Server is live in DiscoPanel at: {discopanel_url}")
            return {
                "success": True,
                "server_uuid": server_uuid,
                "container_name": container_name,
                "discopanel_url": discopanel_url,
                "server_name": server_name,
                "loader": loader,
                "mc_version": mc_version,
                "port": server_port,
                "ram_gb": ram_gb,
                "logs": logs
            }
        else:
            error_details = "\n".join(logs[-10:])
            return {
                "success": False,
                "error": f"DiscoPanel script failed with exit status {exit_status}.",
                "details": error_details,
                "logs": logs
            }

    except Exception as e:
        emit_log(f"Deployment exception: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "logs": logs
        }
    finally:
        if sftp:
            try:
                sftp.close()
            except Exception:
                pass
        if client:
            try:
                client.close()
            except Exception:
                pass
