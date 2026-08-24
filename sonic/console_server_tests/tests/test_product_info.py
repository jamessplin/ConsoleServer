from tests.cli_harness import assert_success
from tests.live_helpers import extract_product_values, normalized


def test_tp_prod_001_show_product_information(cli_for):
    cli = cli_for("product_info")
    result = cli.run("show console-server product-info", privileged=False)
    assert_success(result)
    for field in ("Base Port", "Max Ports", "Max Users", "Max Groups"):
        assert field.lower() in result.stdout.lower()


def test_tp_prod_002_repeat_is_consistent(cli_for):
    cli = cli_for("product_info")
    outputs = [normalized(cli.run("show console-server product-info", privileged=False).stdout) for _ in range(3)]
    assert len(set(outputs)) == 1


def test_tp_prod_003_values_are_valid(cli_for, backend_mode):
    if backend_mode != "live":
        return
    cli = cli_for("product_info")
    result = cli.run("show console-server product-info", privileged=False)
    assert_success(result)
    values = extract_product_values(result.stdout)
    assert set(values) == {"base_port", "max_ports", "max_users", "max_groups"}
    assert all(value > 0 for value in values.values())
    assert values["base_port"] + values["max_ports"] <= 65535
