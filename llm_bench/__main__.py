def main() -> None:
    # Route through the CLI: no subcommand (or `gui`) launches the desktop GUI;
    # `bench` runs a headless benchmark. Keeps `llm-bench` (GUI) backward compatible.
    from llm_bench.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
