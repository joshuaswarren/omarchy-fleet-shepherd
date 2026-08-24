import sys, runpy
with open("bin/fleet-snapshot") as f:
    code = f.read()
namespace = {}
exec(code, namespace)
print(repr(namespace["classify_probe_failure"]("herdr", """{"id":"cli:api:snapshot","error":{"code":"server_not_running","message":"no herdr server is running"}}""")))
