# 3x-ui post install steps

- Login to web panel and change password in Panel Settings -> Auth
- Enable access log for Xray in Xray Configs -> Log -> Access Log
- Change web panel IP Panel Settings -> General -> Listen IP set to 127.0.0.1

## Port forwarding to panel over ssh

```sh
ssh -L 2000:localhost:2053 user@host
```
