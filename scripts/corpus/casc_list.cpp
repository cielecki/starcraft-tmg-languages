// casc_list.cpp - list every file in a CASC storage (name, size, locale flags)
#include "CascLib.h"
#include <cstdio>
#include <cstring>

int main(int argc, char** argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s <storage_path> [substr_filter]\n", argv[0]); return 2; }
    const char* path = argv[1];
    const char* filt = (argc >= 3) ? argv[2] : nullptr;

    HANDLE hStorage = nullptr;
    if (!CascOpenStorage(path, CASC_LOCALE_ALL, &hStorage)) {
        fprintf(stderr, "CascOpenStorage FAILED on %s (err=%d)\n", path, GetCascError());
        return 1;
    }
    CASC_FIND_DATA fd;
    HANDLE hFind = CascFindFirstFile(hStorage, "*", &fd, nullptr);
    if (hFind == nullptr) { fprintf(stderr, "CascFindFirstFile FAILED (err=%d)\n", GetCascError()); CascCloseStorage(hStorage); return 1; }
    long count = 0, shown = 0;
    do {
        count++;
        if (filt == nullptr || strcasestr(fd.szFileName, filt) != nullptr) {
            shown++;
            printf("%s\t%llu\tloc=0x%X\n", fd.szFileName, (unsigned long long)fd.FileSize, fd.dwLocaleFlags);
        }
    } while (CascFindNextFile(hFind, &fd));
    fprintf(stderr, "total=%ld shown=%ld\n", count, shown);
    CascFindClose(hFind);
    CascCloseStorage(hStorage);
    return 0;
}
