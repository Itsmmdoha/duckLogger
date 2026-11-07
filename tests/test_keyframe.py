from keyframe import KeyFrame


def frame(modifiers=0x00, keys=()):
    data = bytearray(11)
    data[3] = modifiers
    for index, key in enumerate(keys):
        data[5 + index] = key
    return data


def test_parses_modifiers_and_keys():
    parser = KeyFrame()
    data = frame(0x01, (0x04, 0x05))
    assert parser.get_modifiers(data) == [-0x01]
    assert parser.get_keys(data) == [0x04, 0x05]
    assert parser.get_all_keys(data) == [-0x01, 0x04, 0x05]


def test_ignores_empty_key_slots():
    parser = KeyFrame()
    data = frame(0x00, (0x04, 0x00, 0x05))
    assert parser.get_keys(data) == [0x04, 0x05]
