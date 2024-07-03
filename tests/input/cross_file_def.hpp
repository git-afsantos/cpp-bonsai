// SPDX-License-Identifier: MIT
// Copyright © 2024 André Santos

#ifndef __CROSS_FILE_DEF_HPP__
#define __CROSS_FILE_DEF_HPP__

namespace aNamespace {

class C {
public:
    void aMethod(int a);
private:
    int x_ = 0;
};

int aFunction(int a);

} // namespace aNamespace

#endif