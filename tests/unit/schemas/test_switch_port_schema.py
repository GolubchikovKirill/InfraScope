import pytest
from pydantic import ValidationError

from app.schemas import (
    SwitchPortAdminStateUpdate,
    SwitchPortPoeUpdate,
    SwitchPortVlanUpdate,
)


def test_port_admin_state_accepts_up_down():
    assert SwitchPortAdminStateUpdate(admin_state="up").admin_state == "up"
    assert SwitchPortAdminStateUpdate(admin_state="down").admin_state == "down"


def test_port_admin_state_rejects_other_value():
    with pytest.raises(ValidationError):
        SwitchPortAdminStateUpdate(admin_state="toggle")


def test_port_vlan_range_validation():
    assert SwitchPortVlanUpdate(vlan=20).vlan == 20
    with pytest.raises(ValidationError):
        SwitchPortVlanUpdate(vlan=5000)


def test_port_poe_actions_validation():
    assert SwitchPortPoeUpdate(action="on").action == "on"
    assert SwitchPortPoeUpdate(action="cycle").action == "cycle"
    with pytest.raises(ValidationError):
        SwitchPortPoeUpdate(action="restart")
