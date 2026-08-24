import sys
with open("bin/fleet-snapshot") as f:
    code = f.read().replace('if __name__ == "__main__":', 'if False:')
    exec(code, globals())
def my_runner(argv, timeout, max_bytes):
    try:
        return run_argv(argv, timeout, max_bytes)
    except Exception as e:
        if hasattr(e, '__context__') and e.__context__:
            print("CONTEXT:", e.__context__)
        raise
try:
    print(my_runner(ssh_omp_argv("home-main"), 20.0, OUTPUT_MAX_BYTES))
except Exception as e:
    print("FAILED:", type(e), str(e))
