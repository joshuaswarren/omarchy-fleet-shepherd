import sys, json
code = open("bin/fleet-snapshot").read().replace('if __name__ == "__main__":', 'if False:')
exec(code, globals())
try:
    obj = parse_json_prefixed(open("/tmp/o.json").read())
    print(list(obj.keys()))
except Exception as e:
    print("FAILED:", type(e), str(e))
