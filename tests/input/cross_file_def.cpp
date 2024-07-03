// SPDX-License-Identifier: MIT
// Copyright © 2024 André Santos

#include "cross_file_def.hpp"

void aNamespace::C::aMethod(int a) {
    x_ = a;
}

int aNamespace::aFunction(int a) {
    return a * a;
}