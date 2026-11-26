# Почта rentoo.uz (mail.rentoo.uz)

Свой почтовый сервер на 169.58.192.146, только пакеты Ubuntu:
Postfix (SMTP 25 / 587 / 465) + Dovecot (IMAP 993, LMTP, SASL) + OpenDKIM (подпись, селектор `mail`).

- Установка / повтор: `bash deploy/mail/setup-mail.sh` на сервере (идемпотентно, ключ DKIM не пересоздаётся).
- Ящики виртуальные: `/var/mail/vhosts/rentoo.uz/<имя>/`, пароли — `/etc/dovecot/users` (SHA512-CRYPT).
- Создать ящик / сменить пароль: `ssh -t root@169.58.192.146 rentoo-mail-passwd info@rentoo.uz`.
- postmaster@, abuse@, admin@, hostmaster@, webmaster@ → info@ (`/etc/postfix/virtual`).
- Сертификат Let's Encrypt `mail.rentoo.uz` (webroot через nginx), после продления — reload postfix/dovecot.
- Только IPv4 (`inet_protocols = ipv4`): на IPv6 нет обратной записи и порт 25 закрыт.

Почтовая программа: IMAP `mail.rentoo.uz:993` SSL; SMTP `mail.rentoo.uz:465` SSL (или 587 STARTTLS);
логин — полный адрес.

DNS (у регистратора, ahost.uz):
- `mail` A 169.58.192.146
- `@` MX 10 mail.rentoo.uz
- `@` TXT `v=spf1 a mx ip4:169.58.192.146 ip4:185.196.212.52 ~all`
- `mail._domainkey` TXT — из `/etc/opendkim/keys/rentoo.uz/mail.txt`
- `_dmarc` TXT `v=DMARC1; p=none; rua=mailto:info@rentoo.uz; fo=1`
- PTR 169.58.192.146 → mail.rentoo.uz (панель Contabo, Reverse DNS)
