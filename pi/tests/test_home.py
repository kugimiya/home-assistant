"""Home Assistant target resolution."""

from jarvis_pi.commands.home import HomeEntity, control_home, resolve_targets


def _lights() -> list[HomeEntity]:
    return [
        HomeEntity("light.zal_1", "Зал 1", "Зал 1", "Зал", "off"),
        HomeEntity("light.zal_2", "Зал 2", "Зал 2", "Зал", "on", "102"),
        HomeEntity("light.zal", "Зал 5", "Зал 5", "Зал", "off"),
        HomeEntity("switch.kitchen", "Чайник", "Чайник", "Kitchen", "off"),
    ]


def test_exact_device_beats_area_prefix() -> None:
    chosen, error = resolve_targets(_lights(), "зал 2")
    assert error is None
    assert [item.entity_id for item in chosen] == ["light.zal_2"]


def test_area_name_selects_lights_in_room() -> None:
    chosen, error = resolve_targets(_lights(), "свет в зале")
    assert error is None
    assert {item.entity_id for item in chosen} == {"light.zal_1", "light.zal_2", "light.zal"}


def test_light_zal_is_not_the_whole_room() -> None:
    chosen, error = resolve_targets(_lights(), "зал 5")
    assert error is None
    assert [item.entity_id for item in chosen] == ["light.zal"]


def test_ambiguous_target() -> None:
    entities = [
        HomeEntity("light.a", "Бра слева", "Бра слева", "Зал", "off"),
        HomeEntity("light.b", "Бра справа", "Бра справа", "Зал", "off"),
    ]
    chosen, error = resolve_targets(entities, "бра")
    assert chosen == []
    assert error and "Бра слева" in error and "Бра справа" in error


def test_control_home_rejects_bad_action_without_network() -> None:
    assert "turn_on" in control_home("зал", "dim")
