if __name__ == "__main__":
    try:
        from beacon.app import run
        run()
    except ModuleNotFoundError as e:
        if "textual" in str(e) or "pyproj" in str(e):
            import sys
            print("Missing dependency. Run from project root: python3 run", file=sys.stderr)
            print("  (or: ./run)", file=sys.stderr)
            sys.exit(1)
        raise
