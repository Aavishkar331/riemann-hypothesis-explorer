"""Stream a .tar.zst of compiled .olean files and extract exact dependencies.

The archive is never stored. Files are unpacked in batches; each batch is
handed to ExtractOleans.lean and deleted as soon as it is done, so disk use
stays at a few batches no matter how large the proof is.

usage: stream_extract.py SOURCE OUT.tsv.gz --lean PATH --extractor PATH
         [--workdir DIR] [--batch 4000] [--jobs 3]
SOURCE is a URL (streamed with curl) or a local .tar.zst file.
"""
import argparse, gzip, os, shutil, subprocess, sys, tarfile, threading, time
from concurrent.futures import ThreadPoolExecutor

PREFIX = ".lake/build/lib/lean/"


def open_stream(source):
    if shutil.which("zstd") is None:      # fallback: Python zstandard (pip install zstandard)
        import zstandard
        if source.startswith(("http://", "https://")):
            curl = subprocess.Popen(["curl", "-sSfL", "--retry", "5", source], stdout=subprocess.PIPE)
            return zstandard.ZstdDecompressor().stream_reader(curl.stdout), [curl]
        return zstandard.ZstdDecompressor().stream_reader(open(source, "rb")), []
    if source.startswith(("http://", "https://")):
        curl = subprocess.Popen(["curl", "-sSfL", "--retry", "5", source], stdout=subprocess.PIPE)
        z = subprocess.Popen(["zstd", "-dc"], stdin=curl.stdout, stdout=subprocess.PIPE)
        curl.stdout.close()
        return z.stdout, [curl, z]
    z = subprocess.Popen(["zstd", "-dc", source], stdout=subprocess.PIPE)
    return z.stdout, [z]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source"); ap.add_argument("out")
    ap.add_argument("--lean", required=True); ap.add_argument("--extractor", required=True)
    ap.add_argument("--workdir", default="olean-work")
    ap.add_argument("--batch", type=int, default=4000); ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--batch-bytes", type=int, default=2 << 30)
    a = ap.parse_args()
    os.makedirs(a.workdir, exist_ok=True)
    pool = ThreadPoolExecutor(a.jobs)
    slots = threading.Semaphore(a.jobs + 1)      # at most jobs running + one filling
    futures, errors = [], []
    t0 = time.time()
    done = {"files": 0, "batches": 0}
    lock = threading.Lock()

    def run(k, bdir, items):
        try:
            lst = os.path.join(bdir, "list.tsv")
            with open(lst, "w") as f:
                for mod, path in items:
                    f.write(f"{mod}\t{path}\n")
            out = os.path.join(a.workdir, f"deps-{k:05d}.tsv")
            r = subprocess.run([a.lean, "--run", a.extractor, lst, out], capture_output=True, text=True)
            if r.returncode != 0:
                errors.append(f"batch {k}: {r.stderr[-2000:]}")
            with lock:
                done["files"] += len(items); done["batches"] += 1
                print(f"  batch {k} done: {done['files']} files total, {time.time() - t0:.0f}s", flush=True)
        finally:
            shutil.rmtree(bdir, ignore_errors=True)
            slots.release()

    stream, procs = open_stream(a.source)
    k, items, bdir, seen, size = 0, [], None, 0, 0
    with tarfile.open(fileobj=stream, mode="r|") as tar:
        for m in tar:
            name = m.name[2:] if m.name.startswith("./") else m.name
            if not (m.isfile() and name.endswith(".olean") and PREFIX in name):
                continue
            rel = name.split(PREFIX, 1)[1]
            if ".." in rel.split("/"):
                continue
            if bdir is None:
                slots.acquire()
                bdir = os.path.join(a.workdir, f"batch-{k:05d}")
                os.makedirs(bdir, exist_ok=True)
            dest = os.path.join(bdir, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with tar.extractfile(m) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            items.append((rel[:-6].replace("/", "."), os.path.abspath(dest)))
            seen += 1
            size += m.size
            if len(items) >= a.batch or size >= a.batch_bytes:
                futures.append(pool.submit(run, k, bdir, items))
                k, items, bdir, size = k + 1, [], None, 0
        if items:
            futures.append(pool.submit(run, k, bdir, items))
            k += 1
    for p in procs:
        p.wait()
        if p.returncode not in (0, None):
            errors.append(f"{p.args[0]} exited with {p.returncode}")
    for f in futures:
        f.result()
    pool.shutdown()
    print(f"{seen} .olean files in {k} batches, {time.time() - t0:.0f}s", flush=True)
    with gzip.open(a.out, "wt", encoding="utf-8", compresslevel=6) as g:
        for i in range(k):
            part = os.path.join(a.workdir, f"deps-{i:05d}.tsv")
            if os.path.exists(part):
                with open(part, encoding="utf-8") as f:
                    shutil.copyfileobj(f, g, 1 << 20)
                os.remove(part)
    if errors:
        print("ERRORS:\n" + "\n".join(errors), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
