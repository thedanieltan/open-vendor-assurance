from tools.openva.discovery_mesh_activation import main


def test_activation_cli_requires_a_command() -> None:
    try:
        main([])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("CLI should require a command")
