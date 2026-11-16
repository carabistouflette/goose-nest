// SPDX-License-Identifier: Apache-2.0
import semver from "./vendor/goose-semver";
import toml from "./vendor/goose-toml";
import nest from ".";
import std;
import os;
fn main() {
    let argv = args();
    if argv.len == 2 && argv[1] == "version" { print("goose-nest ", nest::VERSION); return; }
    if argv.len != 6 || (argv[1] != "resolve" && argv[1] != "fetch" && argv[1] != "offline") {
        print("Usage: nest resolve|fetch|offline REGISTRY PACKAGE REQUIREMENT ABSOLUTE_CACHE\n       nest version");
        if argv.len > 1 { exit(1); } return;
    }
    var resolver = nest::Resolver { cache: str(argv[5]), offline: argv[1] == "offline", .. };
    let requests = [nest::Request { package: str(argv[3]), requirement: str(argv[4]), registry: str(argv[2]) }];
    if !nest::resolve(resolver, requests) { write_stderr(str("nest: ", resolver.error, "\n")); exit(1); }
    for index in resolver.selected {
        let record = nest::record_at(resolver, index);
        if argv[1] != "resolve" { let error = nest::materialize(record, resolver.cache, resolver.offline); if error.len > 0 { write_stderr(str("nest: ", error, "\n")); exit(1); } }
        print(record.package, " ", record.version, " ", record.sha256);
    }
}
