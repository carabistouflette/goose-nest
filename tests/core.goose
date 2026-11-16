// SPDX-License-Identifier: Apache-2.0
import semver from "../vendor/goose-semver";
import toml from "../vendor/goose-toml";
import nest from "..";
import std;
fn record(package: u8[:], version: u8[:], dependencies: const nest::Dependency[:]) -> nest::Record {
    var owned: nest::Dependency[>..] = []; for dep in dependencies { owned.push(copy(dep)); }
    nest::Record { package: str(package), version: str(version), registry: str("https://example.com/index"), url: str("https://example.com/a.tar.gz"), sha256: str("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"), entry: str("lib.goose"), dependencies: copy(owned), .. }
}
fn selected_version(r: const nest::Resolver&, package: u8[:]) -> u8[>..] {
    for i in r.selected { let value = nest::record_at(r, i); if value.package == package { return str(value.version); } } return [];
}
fn main() {
    assert(nest::package_name("goose-json")); assert(!nest::package_name("../json")); assert(!nest::package_name("goose_json"));
    assert(!nest::registry_url("https://example.com/index/")); assert(!nest::url("http://example.com"));
    assert(nest::matches("^1.0.0", "1.9.0")); assert(!nest::matches("^1.0.0", "2.0.0")); assert(!nest::matches("^1.0.0", "1.1.0-alpha.1"));
    let root = [nest::Request { package: str("app"), requirement: str("^1.0.0"), registry: str("https://example.com/index") }];
    let both = [nest::Dependency { alias: str("left"), package: str("left"), requirement: str("^1.0.0") }, nest::Dependency { alias: str("right"), package: str("right"), requirement: str("^1.0.0") }];
    let exact_one = [nest::Dependency { alias: str("shared"), package: str("shared"), requirement: str("=1.0.0") }];
    let exact_two = [nest::Dependency { alias: str("shared"), package: str("shared"), requirement: str("=2.0.0") }];
    var none: nest::Dependency[>..] = [];
    var r = nest::Resolver { .. };
    r.locked_records.push(record("app", "1.0.0", both));
    r.locked_records.push(record("left", "1.1.0", exact_two));
    r.locked_records.push(record("left", "1.0.0", exact_one));
    r.locked_records.push(record("right", "1.0.0", exact_one));
    r.locked_records.push(record("shared", "1.0.0", none));
    r.locked_records.push(record("shared", "2.0.0", none));
    assert(nest::resolve(r, root)); assert(selected_version(r, "left") == "1.0.0"); assert(selected_version(r, "shared") == "1.0.0");
    // A failing branch must restore all pending siblings, not just their count.
    assert(r.selected.len == 4);
    let serialized = nest::record_text(nest::record_at(r, r.selected[0]));
    let decoded, error = nest::locked_record(serialized, "https://example.com/index", "app");
    assert(error.len == 0 && decoded.dependencies.len == 2 && nest::valid(decoded));
    var invalid: nest::Record[>..] = [];
    assert(nest::parse_index("schema = 2\npackage = 'app'\nreleases = []", "https://example.com/index", "app", invalid).len > 0);
    let impossible = [nest::Request { package: str("app"), requirement: str("=2.0.0"), registry: str("https://example.com/index") }];
    r.locked = true; assert(!nest::resolve(r, impossible)); assert(r.error.len > 0);
    print("registry core contracts passed");
}
