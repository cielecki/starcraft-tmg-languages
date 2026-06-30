// casc_grab.cpp - enumerate storage, for every file whose name CONTAINS <substr>,
// extract it by its exact EKey (from CASC_FIND_DATA) into <outdir>/<sanitized>.bin
#include "CascLib.h"
#include <cstdio>
#include <cstring>
#include <string>

static std::string sanitize(const char* s) {
    std::string r(s);
    for (auto& c : r) if (c=='\\' || c=='/' || c==':' || c=='*' || c=='?' ) c='_';
    return r;
}

int main(int argc, char** argv) {
    if (argc < 4) { fprintf(stderr, "usage: %s <storage> <name_substr> <outdir>\n", argv[0]); return 2; }
    const char* path = argv[1];
    const char* filt = argv[2];
    const char* outdir = argv[3];

    HANDLE hStorage = nullptr;
    if (!CascOpenStorage(path, CASC_LOCALE_ALL, &hStorage)) {
        fprintf(stderr, "CascOpenStorage FAILED (err=%d)\n", GetCascError()); return 1;
    }
    CASC_FIND_DATA fd;
    HANDLE hFind = CascFindFirstFile(hStorage, "*", &fd, nullptr);
    if (!hFind) { fprintf(stderr, "FindFirst FAILED (err=%d)\n", GetCascError()); return 1; }
    int n = 0;
    do {
        if (!strcasestr(fd.szFileName, filt)) continue;
        // Open by EKey for the exact span this find entry refers to.
        HANDLE hFile = nullptr;
        bool ok = CascOpenFile(hStorage, fd.EKey, CASC_LOCALE_ALL, CASC_OPEN_BY_EKEY, &hFile);
        if (!ok) { fprintf(stderr, "open EKEY fail %s (err=%d)\n", fd.szFileName, GetCascError()); continue; }
        std::string outpath = std::string(outdir) + "/" + sanitize(fd.szFileName) + ".bin";
        FILE* fo = fopen(outpath.c_str(), "wb");
        if (!fo) { fprintf(stderr, "cannot write %s\n", outpath.c_str()); CascCloseFile(hFile); continue; }
        char buf[65536]; DWORD got=0; unsigned long long tot=0;
        while (CascReadFile(hFile, buf, sizeof(buf), &got) && got>0) { fwrite(buf,1,got,fo); tot+=got; }
        fclose(fo);
        fprintf(stderr, "%llu bytes\t%s\n", tot, fd.szFileName);
        CascCloseFile(hFile);
        n++;
    } while (CascFindNextFile(hFind, &fd));
    fprintf(stderr, "done, %d files\n", n);
    CascFindClose(hFind);
    CascCloseStorage(hStorage);
    return 0;
}
