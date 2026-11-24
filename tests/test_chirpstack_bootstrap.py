"""Bootstrap defaults must never overwrite administrator-owned ChirpStack state."""

from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

from scripts.provision_chirpstack import DEFAULT_JOIN_EUI, DEVICES, GATEWAYS, provision


class ChirpStackFixture:
    names = {"tenants": "tenant", "device-profiles": "deviceProfile",
             "applications": "application", "gateways": "gateway", "devices": "device"}

    def __init__(self):
        self.resources = {name: {} for name in self.names}
        self.keys = {}
        self.calls = []
        self.sequence = 0

    def request(self, method, path, body=None, *, allow_missing=False):
        self.calls.append((method, path, deepcopy(body)))
        assert method in {"GET", "POST"}, "Bootstrap attempted to modify an existing resource"
        url = urlsplit(path)
        parts = url.path.strip("/").split("/")
        collection = parts[0]
        if method == "GET":
            if len(parts) == 3 and parts[2] == "keys":
                return {"deviceKeys": deepcopy(self.keys[parts[1]])} if parts[1] in self.keys else {}
            if len(parts) == 2:
                resource = self.resources[collection].get(parts[1])
                assert resource or allow_missing, f"Unexpected missing resource: {path}"
                return {self.names[collection]: deepcopy(resource)} if resource else {}
            query = parse_qs(url.query)
            result = [deepcopy(resource) for resource in self.resources[collection].values()
                      if query.get("search", [""])[0] in resource.get("name", "")
                      and ("tenantId" not in query or resource.get("tenantId") == query["tenantId"][0])]
            return {"result": result, "totalCount": len(result)}
        if len(parts) == 3 and parts[2] == "keys":
            assert parts[1] not in self.keys, "Existing device keys were overwritten"
            self.keys[parts[1]] = deepcopy(body["deviceKeys"])
            return {}
        resource = deepcopy(body[self.names[collection]])
        self.sequence += 1
        identity = (resource.get("devEui") or resource.get("gatewayId")
                    or f"{collection}-{self.sequence}")
        assert identity not in self.resources[collection], "Existing resource was recreated"
        if collection not in {"devices", "gateways"}:
            resource["id"] = identity
        self.resources[collection][identity] = resource
        return {"id": identity}


def test_fresh_bootstrap_creates_inventory_and_keys_once():
    api = ChirpStackFixture()
    ids = provision(api, "A"*32, DEFAULT_JOIN_EUI)
    assert len(api.resources["tenants"]) == 1
    assert len(api.resources["device-profiles"]) == 1
    assert len(api.resources["applications"]) == 1
    assert len(api.resources["gateways"]) == len(GATEWAYS)
    assert len(api.resources["devices"]) == len(DEVICES)
    assert set(ids) == {"tenant", "profile", "application"}
    assert len(api.keys) == len(DEVICES)
    assert all(keys == {"nwkKey": "A"*32} for keys in api.keys.values())


def test_bootstrap_preserves_renamed_resources_custom_settings_and_individual_keys():
    api = ChirpStackFixture()
    ids = provision(api, "A"*32, DEFAULT_JOIN_EUI)
    api.resources["tenants"][ids["tenant"]].update(name="My renamed tenant", canHaveGateways=False)
    api.resources["device-profiles"][ids["profile"]].update(
        name="My custom profile", macVersion="LORAWAN_1_0_4", regParamsRevision="RP002_1_0_3",
        payloadCodecScript="custom decoder", autoDetectMeasurements=False,
    )
    api.resources["applications"][ids["application"]].update(name="My renamed app", description="Keep me")
    for gateway in api.resources["gateways"].values():
        gateway.update(name="Custom gateway name", description="Custom antenna", downlinkPriority=7)
    for index, (eui, *_) in enumerate(DEVICES):
        api.resources["devices"][eui].update(
            name=f"Custom sensor {index}", joinEui="0011223344556677", isDisabled=True,
            skipFcntCheck=True, tags={"room": "Custom room", "owner": "Facilities"},
            applicationId="another-app", deviceProfileId="another-profile",
        )
        api.keys[eui] = {"nwkKey": f"{index:032x}", "appKey": "B"*32}
    before = deepcopy((api.resources, api.keys))
    api.calls.clear()
    assert provision(api, "C"*32, "ffeeddccbbaa0099", ids) == ids
    assert (api.resources, api.keys) == before
    assert all(method == "GET" for method, _, _ in api.calls)


def test_existing_renamed_deployment_is_adopted_by_eui_without_saved_ids():
    api = ChirpStackFixture()
    ids = provision(api, "A"*32, DEFAULT_JOIN_EUI)
    for collection in ("tenants", "device-profiles", "applications"):
        for resource in api.resources[collection].values():
            resource["name"] = "Renamed in ChirpStack UI"
    before = deepcopy((api.resources, api.keys))
    api.calls.clear()
    assert provision(api, "B"*32, DEFAULT_JOIN_EUI) == ids
    assert (api.resources, api.keys) == before
    assert all(method == "GET" for method, _, _ in api.calls)


def test_explicit_bootstrap_only_recreates_missing_inventory():
    api = ChirpStackFixture()
    ids = provision(api, "A"*32, DEFAULT_JOIN_EUI)
    missing_device = DEVICES[-1][0]
    missing_gateway = GATEWAYS[-1][0]
    del api.resources["devices"][missing_device]
    del api.keys[missing_device]
    del api.resources["gateways"][missing_gateway]
    retained_device = DEVICES[0][0]
    api.resources["devices"][retained_device]["isDisabled"] = True
    api.keys[retained_device] = {"nwkKey": "B"*32}
    api.calls.clear()
    provision(api, "C"*32, DEFAULT_JOIN_EUI, ids)
    assert api.resources["devices"][retained_device]["isDisabled"] is True
    assert api.keys[retained_device] == {"nwkKey": "B"*32}
    assert api.keys[missing_device] == {"nwkKey": "C"*32}
    assert {path for method, path, _ in api.calls if method == "POST"} == {
        "/gateways", "/devices", f"/devices/{missing_device}/keys",
    }


def test_existing_device_without_otaa_keys_is_not_silently_given_new_keys():
    api = ChirpStackFixture()
    ids = provision(api, "A"*32, DEFAULT_JOIN_EUI)
    device = DEVICES[0][0]
    del api.keys[device]
    provision(api, "B"*32, DEFAULT_JOIN_EUI, ids)
    assert device not in api.keys
