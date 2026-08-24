import sys
with open("bin/fleet-snapshot") as f:
    code = f.read().replace('if __name__ == "__main__":', 'if False:')
    exec(code, globals())
try:
    print("Testing home-main...")
    out = probe_one({"id":"home-main", "mode":"ssh", "target":"home-main", "label":"x"}, "omp", 20.0, run_argv)
    print("SUCCESS", len(out))
except Exception as e:
    print("FAILED:", type(e), str(e))
