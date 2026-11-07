"""Whole-network plan validation and per-device settings rendering.

This module intentionally uses only the Python standard library.  It runs on
the provisioning host; rendered settings are consumed by MicroPython devices.
"""

import copy
import json
import os


SUPPORTED_PROTOCOL_VERSION = 4
DELIVERY_MODES = ("best", "primary", "all")
GATEWAY_EGRESS = ("wifi", "lora", "sendmy", "log")


class PlanError(ValueError):
    pass


def _placeholder(value):
    text = str(value or "").strip()
    return not text or text.upper().startswith("CHANGE_ME")


def _devices(plan):
    result = []
    for role, key in (("gateway", "gateways"), ("node", "implants")):
        for device in plan.get(key, []):
            item = dict(device)
            item["role"] = role
            result.append(item)
    sink = plan.get("lora_sink")
    if sink:
        item = dict(sink)
        item["role"] = "lora_sink"
        result.append(item)
    return result


def validate_plan(plan):
    if not isinstance(plan, dict):
        raise PlanError("network plan must be an object")
    network = plan.get("network")
    if not isinstance(network, dict):
        raise PlanError("network is required")
    if not network.get("id"):
        raise PlanError("network.id is required")
    if network.get("protocol_version") != SUPPORTED_PROTOCOL_VERSION:
        raise PlanError("network.protocol_version must be 4")
    if not isinstance(network.get("channel"), int) or not 1 <= network["channel"] <= 14:
        raise PlanError("network.channel must be between 1 and 14")
    peer_key = network.get("peer_key", "")
    if len(peer_key.encode("utf-8")) != 16 or peer_key.startswith("CHANGE_ME"):
        raise PlanError("network.peer_key must contain exactly 16 non-placeholder bytes")

    gateways = plan.get("gateways", [])
    implants = plan.get("implants", [])
    if not gateways:
        raise PlanError("at least one gateway is required")
    if not implants:
        raise PlanError("at least one implant is required")

    ids = set()
    macs = set()
    for device in _devices(plan):
        device_id = device.get("id", "")
        mac = str(device.get("mac", "")).lower().replace("-", ":")
        if not device_id or device_id in ids:
            raise PlanError("device IDs must be present and unique")
        if not _valid_mac(mac) or mac in macs:
            raise PlanError("device MACs must be valid unicast addresses and unique")
        ids.add(device_id)
        macs.add(mac)
        management = device.get("management", {})
        if management.get("enabled"):
            if (_placeholder(management.get("password")) or
                    len(str(management.get("password", ""))) < 8):
                raise PlanError("management password must be a non-placeholder value")
            if (_placeholder(management.get("api_token")) or
                    len(str(management.get("api_token", ""))) < 16):
                raise PlanError("management API token must be a non-placeholder value")

    gateway_ids = [gateway["id"] for gateway in gateways]
    direct_sendmy = False
    lora_gateways = []
    for implant in implants:
        uplink = implant.get("uplink", {})
        mesh_enabled = bool(uplink.get("mesh", False))
        sendmy_enabled = bool(uplink.get("sendmy", False))
        if not mesh_enabled and not sendmy_enabled:
            raise PlanError("implant %s must enable mesh or sendmy" % implant["id"])
        direct_sendmy = direct_sendmy or sendmy_enabled
        delivery = implant.get("delivery", {})
        mode = delivery.get("mode", "best")
        targets = delivery.get("gateways", gateway_ids)
        if mode not in DELIVERY_MODES:
            raise PlanError("invalid delivery mode for %s" % implant["id"])
        if not targets or any(target not in gateway_ids for target in targets):
            raise PlanError("implant %s references an unknown gateway" % implant["id"])

    for gateway in gateways:
        backends = gateway.get("egress", [])
        if isinstance(backends, str):
            backends = [backends]
        if not backends or any(backend not in GATEWAY_EGRESS for backend in backends):
            raise PlanError("gateway %s needs supported egress" % gateway["id"])
        if direct_sendmy and "sendmy" in backends:
            raise PlanError("gateway sendmy conflicts with direct implant sendmy")
        if "lora" in backends:
            lora_gateways.append(gateway)
        if "wifi" in backends and not gateway.get("wifi", {}).get("url"):
            raise PlanError("gateway %s wifi egress requires a URL" % gateway["id"])

    if lora_gateways:
        if not plan.get("lora_sink"):
            raise PlanError("lora_sink is required when a gateway uses lora")
        if not plan["lora_sink"].get("management", {}).get("enabled"):
            raise PlanError("lora_sink requires management.enabled=true")
        sink_lora = plan.get("lora_sink", {}).get("lora", plan.get("lora", {}))
        if not sink_lora:
            raise PlanError("LoRa settings are required")
        if (_placeholder(sink_lora.get("key")) or
                len(str(sink_lora.get("key", "")).encode("utf-8")) < 16):
            raise PlanError("LoRa key must be a non-placeholder value")
        for gateway in lora_gateways:
            gateway_lora = gateway.get("lora", plan.get("lora", {}))
            if gateway_lora != sink_lora:
                raise PlanError("gateway and lora_sink LoRa settings must match")
    if direct_sendmy or any("sendmy" in (gateway.get("egress", [])
                                         if not isinstance(gateway.get("egress", []), str)
                                         else [gateway.get("egress")])
                            for gateway in gateways):
        sendmy = plan.get("sendmy", {})
        if not sendmy.get("modem_id"):
            raise PlanError("sendmy.modem_id is required")
        if not 32 <= int(sendmy.get("max_message_bytes", 180)) <= 220:
            raise PlanError("sendmy.max_message_bytes must be between 32 and 220")
        if not 1000 <= int(sendmy.get("batch_interval_ms", 60000)) <= 86400000:
            raise PlanError(
                "sendmy.batch_interval_ms must be between 1000 and 86400000"
            )
        if not 1 <= int(sendmy.get("batch_size", 32)) <= 256:
            raise PlanError("sendmy.batch_size must be between 1 and 256")
    return True


def _valid_mac(value):
    try:
        parts = value.split(":")
        raw = bytes(int(part, 16) for part in parts)
        return (len(parts) == 6 and all(len(part) == 2 for part in parts)
                and any(raw) and not raw[0] & 1)
    except (TypeError, ValueError):
        return False


def render_settings(plan):
    """Return ``{device_id: settings_dict}`` after whole-plan validation."""
    validate_plan(plan)
    network = plan["network"]
    devices = _devices(plan)
    peer_macs = {item["id"]: item["mac"] for item in devices}
    gateway_ids = [item["id"] for item in plan["gateways"]]
    direct_sendmy = any(item.get("uplink", {}).get("sendmy", False)
                        for item in plan["implants"])
    rendered = {}
    for item in devices:
        role = item["role"]
        device_id = item["id"]
        settings = {
            "device": {
                "role": role,
                "id": device_id,
                "mesh_only": role in ("node", "gateway"),
                "data_source": role == "node",
                "relay": bool(item.get("relay", role == "node")),
                "local_ui": role in ("gateway", "lora_sink"),
            },
            "management": copy.deepcopy(item.get("management", {"enabled": False})),
            "network_policy": {"direct_sendmy": direct_sendmy},
        }
        if role in ("node", "gateway"):
            settings["mesh"] = {
                "enabled": True,
                "transport": "espnow",
                "network_id": network["id"],
                "protocol_version": SUPPORTED_PROTOCOL_VERSION,
                "channel": network["channel"],
                "peer_key": network["peer_key"],
                "peer_macs": {key: value for key, value in peer_macs.items()
                              if key != device_id and key != plan.get("lora_sink", {}).get("id")},
            }
        else:
            settings["mesh"] = {"enabled": False}
        if role == "node":
            settings["uplink"] = copy.deepcopy(item.get("uplink", {}))
            delivery = copy.deepcopy(item.get("delivery", {}))
            delivery.setdefault("mode", "best")
            delivery.setdefault("gateways", gateway_ids)
            settings["delivery"] = delivery
        elif role == "gateway":
            backends = item.get("egress", [])
            if isinstance(backends, str):
                backends = [backends]
            settings["egress"] = copy.deepcopy(item.get("egress_settings", {}))
            settings["egress"].update({
                "enabled": True,
                "backends": list(backends),
                "backend": backends[0],
            })
            if "wifi" in backends:
                settings["egress"]["url"] = item.get("wifi", {}).get("url", "")
        if role == "lora_sink" or "lora" in item.get("egress", []):
            settings["lora"] = copy.deepcopy(item.get("lora", plan.get("lora", {})))
        if role == "lora_sink":
            settings["storage"] = copy.deepcopy(item.get("storage", {}))
        if item.get("uplink", {}).get("sendmy") or "sendmy" in item.get("egress", []):
            settings["sendmy"] = copy.deepcopy(
                item.get("sendmy", plan.get("sendmy", {}))
            )
            settings["sendmy"]["enabled"] = True
        rendered[device_id] = settings
    return rendered


def load_plan(path):
    with open(path, "r") as plan_file:
        return json.load(plan_file)


def write_rendered(plan_path, output_directory):
    plan = load_plan(plan_path)
    rendered = render_settings(plan)
    if not os.path.isdir(output_directory):
        os.makedirs(output_directory)
    for device_id, settings in rendered.items():
        path = os.path.join(output_directory, device_id + ".json")
        with open(path, "w") as settings_file:
            json.dump(settings, settings_file, indent=2, sort_keys=True)
            settings_file.write("\n")
    summary = os.path.join(output_directory, "network-plan.rendered.json")
    with open(summary, "w") as rendered_file:
        json.dump({"plan": plan, "settings": rendered}, rendered_file,
                  indent=2, sort_keys=True)
        rendered_file.write("\n")
    manifest = os.path.join(output_directory, "device-manifest.tsv")
    with open(manifest, "w") as manifest_file:
        manifest_file.write("device_id\tmac\trole\n")
        for device in _devices(plan):
            manifest_file.write("%s\t%s\t%s\n" % (
                device["id"], str(device["mac"]).lower(), device["role"]
            ))
    return rendered


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Validate and render a MeshOps network plan")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--print", action="store_true", dest="print_rendered")
    args = parser.parse_args(argv)
    rendered = write_rendered(args.plan, args.output)
    if args.print_rendered:
        print(json.dumps(rendered, indent=2, sort_keys=True))
    else:
        print("validated %d devices" % len(rendered))


if __name__ == "__main__":
    main()
