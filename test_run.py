import sys
with open("bin/fleet-snapshot") as f:
    code = f.read().replace('if __name__ == "__main__":\n    sys.exit(main())', '')
    exec(code, globals())

try:
    print(repr(run_argv(ssh_herdr_argv("clients-main"), 10.0)))
except Exception as e:
    print(f"Exception: {type(e).__name__}: {e}")
    if isinstance(e, _NonZeroExit):
        print("Output:", repr(str(e)))
