import ftplib, io, os, time

# The gated dashboard lives at <docroot>/looreadykpi/private/dashboard.html.
# The FTP account may be chrooted to public_html (so paths are relative to it)
# or to the home dir (so they must include public_html). Try both; the first
# that succeeds wins. pwd() is logged so the working layout is visible.
d = open('/tmp/live.html', 'rb').read()

candidates = [
    'looreadykpi/private/dashboard.html',              # FTP root == public_html
    'public_html/looreadykpi/private/dashboard.html',  # FTP root == home
]

ok = False
for attempt in range(3):
    if ok:
        break
    try:
        f = ftplib.FTP()
        f.connect('145.79.209.123', 21, timeout=60)
        f.login('u133013644', os.environ['FTP_PASS'])
        try:
            print('FTP root (pwd):', f.pwd())
        except Exception:
            pass
        for path in candidates:
            try:
                f.storbinary('STOR ' + path, io.BytesIO(d))
                print('done', len(d), 'via', path)
                ok = True
                break
            except Exception as e:
                print('path failed:', path, '->', str(e))
        f.quit()
    except Exception as e:
        print('Attempt', attempt + 1, 'failed:', str(e))
        if attempt < 2:
            time.sleep(10)

if not ok:
    print('All FTP attempts failed')
