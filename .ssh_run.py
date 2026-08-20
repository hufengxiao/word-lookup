# -*- coding: utf-8 -*-
"""在 NAS 上运行指定脚本: python3 .ssh_run.py <local_script.py>"""
import sys, paramiko
script = sys.argv[1]
pw = "Hongxinzhijia"
data = open(script, "rb").read()
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("192.168.71.51", username="captshaw", password=pw, timeout=25)
stdin, stdout, stderr = ssh.exec_command("cd ~/Projects/oxford-lookup && python3 -")
stdin.write(data.decode("utf-8"))
stdin.channel.shutdown_write()
out = stdout.read().decode("utf-8", "replace")
err = stderr.read().decode("utf-8", "replace")
if out:
    print("=== STDOUT ===")
    print(out)
if err.strip():
    print("=== STDERR ===")
    print(err.strip()[:4000])
ssh.close()