// casc_online.cpp - open an ONLINE CASC storage and fetch files whose name contains <substr> (plPL).
// usage: casc_online <cache_dir> <product_codename> <region> <name_substr> <outdir>
#include "CascLib.h"
#include <cstdio>
#include <cstring>
#include <string>

#define CASC_LOCALE_PLPL 0x00020000

static std::string sanitize(const char* s){ std::string r(s); for(auto&c:r) if(c=='\\'||c=='/'||c==':'||c=='*'||c=='?')c='_'; return r; }

static bool WINAPI progress(void*, CASC_PROGRESS_MSG msg, LPCSTR obj, DWORD cur, DWORD tot){
    if (msg==CascProgressLoadingManifest || msg==CascProgressDownloadingArchiveIndexes)
        fprintf(stderr, "[load] %s %u/%u\n", obj?obj:"", cur, tot);
    return false; // don't cancel
}

int main(int argc, char** argv){
    if (argc < 6){ fprintf(stderr,"usage: %s <cache_dir> <product> <region> <name_substr> <outdir>\n", argv[0]); return 2; }
    const char* cache=argv[1]; const char* product=argv[2]; const char* region=argv[3];
    const char* filt=argv[4]; const char* outdir=argv[5];

    CASC_OPEN_STORAGE_ARGS args; memset(&args,0,sizeof(args));
    args.Size = sizeof(args);
    args.szLocalPath = cache;       // online: local cache path
    args.szCodeName  = product;     // e.g. "s1" / "sc1live" / "s2"
    args.szRegion    = region;      // e.g. "us" / "eu"
    args.PfnProgressCallback = progress;
    args.dwLocaleMask = CASC_LOCALE_PLPL | CASC_LOCALE_ENUS;

    HANDLE hStorage=nullptr;
    if (!CascOpenStorageEx(nullptr, &args, true, &hStorage)){
        fprintf(stderr,"CascOpenStorageEx ONLINE FAILED (err=%d)\n", GetCascError());
        return 1;
    }
    fprintf(stderr,"online storage opened.\n");
    CASC_FIND_DATA fd; HANDLE hF=CascFindFirstFile(hStorage,"*",&fd,nullptr);
    if(!hF){ fprintf(stderr,"FindFirst FAILED (err=%d)\n",GetCascError()); return 1; }
    int n=0;
    do{
        if(!strcasestr(fd.szFileName, filt)) continue;
        HANDLE hFile=nullptr;
        if(!CascOpenFile(hStorage, fd.EKey, CASC_LOCALE_ALL, CASC_OPEN_BY_EKEY, &hFile)){
            fprintf(stderr,"open fail %s (err=%d)\n", fd.szFileName, GetCascError()); continue;
        }
        std::string op = std::string(outdir)+"/"+sanitize(fd.szFileName)+".bin";
        FILE* fo=fopen(op.c_str(),"wb");
        char buf[65536]; DWORD got=0; unsigned long long tot=0;
        while(CascReadFile(hFile,buf,sizeof(buf),&got)&&got>0){ fwrite(buf,1,got,fo); tot+=got; }
        fclose(fo);
        fprintf(stderr,"%llu bytes\t%s\n", tot, fd.szFileName);
        CascCloseFile(hFile); n++;
    }while(CascFindNextFile(hF,&fd));
    fprintf(stderr,"done %d files\n", n);
    CascFindClose(hF); CascCloseStorage(hStorage); return 0;
}
