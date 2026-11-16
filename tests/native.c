// SPDX-License-Identifier: Apache-2.0
#include "../native/nest.c"
#include <assert.h>
int main(void) {
    assert(safe_relative("source/lib.goose"));
    assert(!safe_relative("../outside")); assert(!safe_relative("a/../outside"));
    assert(!safe_relative("a//b")); assert(!safe_relative("a\\b"));
    assert(!safe_relative("/absolute")); assert(!safe_relative("a/./b"));
    assert(!safe_relative("a/")); assert(!safe_relative("a\nb"));
    char hash[65]; assert(digest("abc", 3, hash));
    assert(!strcmp(hash, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"));
    char temp[] = "/tmp/nest-native-XXXXXX"; assert(mkdtemp(temp));
    char path[PATH_CAP]; assert(join(path, temp, "payload"));
    assert(write_file(path, "data", 4));
    uint8_t out[4]; assert(read_file(path, out, sizeof out) == 4 && !memcmp(out, "data", 4));
    assert(read_file(path, out, 3) == -1);
    char first[65], second[65]; assert(tree_digest(temp, first));
    assert(write_file(path, "date", 4)); assert(tree_digest(temp, second)); assert(strcmp(first, second));
    unlink(path); assert(symlink("/etc/passwd", path) == 0); assert(!tree_digest(temp, second));
    remove_private(temp);
    puts("native cache contracts passed");
}
