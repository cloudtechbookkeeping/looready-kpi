import ftplib, io, os, time

# Upload the freshly built dashboard to <docroot>/looreadykpi/private/dashboard.html.
# The FTP account's root varies (public_html chroot, home dir, or the domains path),
# and some servers reject a multi-segment STOR path, so CWD into the directory
# step-by-step and STOR a bare filename. Diagnostics go to the job summary.
d = open('/tmp/live.html', 'rb').read()
summary = os.environ.get('GITHUB_STEP_SUMMARY')
log = []
def note(m):
    print(m)
    log.append(str(m))

# Directory (not file) candidates, ordered by most likely FTP root first.
candidates = [
    'looreadykpi/private',                                              # root == public_html
    'public_html/looreadykpi/private',                                 # root == home
    'domains/cloudtechbookkeeping.com/public_html/looreadykpi/private', # root == home (real path)
]

def put(f):
    try: note('pwd=' + f.pwd())
    except Exception as e: note('pwd err ' + str(e))
    try: note('root nlst=' + ','.join(f.nlst()))
    except Exception as e: note('nlst err ' + str(e))
    for base in candidates:
        try:
            f.cwd('/')
        except Exception:
            pass
        okcwd = True
        for part in [p for p in base.split('/') if p]:
            try:
                f.cwd(part)
            except Exception as e:
                note('cwd fail [' + base + '] at "' + part + '": ' + str(e))
                okcwd = False
                break
        if not okcwd:
            continue
        try:
            f.storbinary('STOR dashboard.html', io.BytesIO(d))
            note('STORED ' + str(len(d)) + ' bytes via ' + base)
            return True
        except Exception as e:
            note('store fail [' + base + ']: ' + str(e))
    return False

ok = False
for attempt in range(3):
    if ok:
        break
    try:
        f = ftplib.FTP()
        f.connect('145.79.209.123', 21, timeout=60)
        f.login('u133013644', os.environ['FTP_PASS'])
        f.set_pasv(True)
        ok = put(f)
        try:
            f.quit()
        except Exception:
            pass
    except Exception as e:
        note('Attempt ' + str(attempt + 1) + ' connect failed: ' + str(e))
        if attempt < 2:
            time.sleep(10)

note('RESULT: ' + ('OK' if ok else 'FAILED'))
if summary:
    try:
        with open(summary, 'a') as sf:
            sf.write('\n### FTP deploy\n```\n' + '\n'.join(log) + '\n```\n')
    except Exception:
        pass
if not ok:
    print('All FTP attempts failed')
