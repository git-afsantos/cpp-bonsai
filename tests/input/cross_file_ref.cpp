// SPDX-License-Identifier: MIT
// Copyright © 2024 André Santos

#include "cross_file_def.hpp"

int main(int argc, char **argv) {
    aNamespace::C c;
    int a = aNamespace::aFunction(2);
    c.aMethod(a);
    return 0;
}