import ftplib, io, os, time

d = open('/tmp/live.html', 'rb').read()
for i in range(3):
    try:
        f = ftplib.FTP()
        f.connect('145.79.209.123', 21, timeout=60)
        f.login('u133013644', os.environ['FTP_PASS'])
        f.storbinary('STOR /public_html/looreadykpi/index.html', io.BytesIO(d))
        f.quit()
        print('done', len(d))
        break
    except Exception as e:
        print('Attempt', i+1, 'failed:', str(e))
        if i < 2:
            time.sleep(15)
else:
    print('All FTP attempts failed')
