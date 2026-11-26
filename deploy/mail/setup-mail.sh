#!/bin/bash
# Почтовый сервер rentoo.uz: Postfix (SMTP) + Dovecot (IMAP, LMTP, SASL) + OpenDKIM.
# Только пакеты Ubuntu. Ящики — виртуальные (/var/mail/vhosts), пароли — /etc/dovecot/users.
set -euo pipefail
DOMAIN=rentoo.uz
HOST=mail.rentoo.uz
SELECTOR=mail
VMAIL_UID=5000

export DEBIAN_FRONTEND=noninteractive
echo "postfix postfix/main_mailer_type select Internet Site" | debconf-set-selections
echo "postfix postfix/mailname string $DOMAIN" | debconf-set-selections
apt-get update -qq
apt-get install -y -qq postfix dovecot-core dovecot-imapd dovecot-lmtpd opendkim opendkim-tools >/dev/null
echo "$DOMAIN" > /etc/mailname

# ── Сертификат для mail.rentoo.uz (http-01 через nginx) ──────────────────────
mkdir -p /var/www/letsencrypt
cat > /etc/nginx/sites-available/$HOST <<EOF
server {
    listen 80;
    server_name $HOST;
    location /.well-known/acme-challenge/ { root /var/www/letsencrypt; }
    location / { return 301 https://$DOMAIN/help; }
}
EOF
ln -sfn /etc/nginx/sites-available/$HOST /etc/nginx/sites-enabled/$HOST
nginx -t -q && systemctl reload nginx
if [ ! -f /etc/letsencrypt/live/$HOST/fullchain.pem ]; then
  certbot certonly --webroot -w /var/www/letsencrypt -d $HOST --non-interactive --agree-tos \
    --register-unsafely-without-email --keep-until-expiring -q
fi
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/mail-reload.sh <<'EOF'
#!/bin/sh
systemctl reload postfix dovecot 2>/dev/null || true
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/mail-reload.sh
CERT=/etc/letsencrypt/live/$HOST/fullchain.pem
KEY=/etc/letsencrypt/live/$HOST/privkey.pem

# ── Пользователь хранилища ──────────────────────────────────────────────────
getent group vmail >/dev/null || groupadd -g $VMAIL_UID vmail
id vmail >/dev/null 2>&1 || useradd -u $VMAIL_UID -g vmail -d /var/mail/vhosts -s /usr/sbin/nologin -M vmail
mkdir -p /var/mail/vhosts/$DOMAIN
chown -R vmail:vmail /var/mail/vhosts
chmod 770 /var/mail/vhosts

# ── Dovecot ─────────────────────────────────────────────────────────────────
# Только виртуальные ящики: системные пользователи (PAM) почтой не входят.
sed -i 's/^!include auth-system.conf.ext/#!include auth-system.conf.ext/' /etc/dovecot/conf.d/10-auth.conf
touch /etc/dovecot/users
chown root:dovecot /etc/dovecot/users
chmod 640 /etc/dovecot/users
cat > /etc/dovecot/local.conf <<EOF
protocols = imap lmtp
listen = *
mail_location = maildir:/var/mail/vhosts/%d/%n
mail_uid = vmail
mail_gid = vmail
first_valid_uid = $VMAIL_UID
mail_privileged_group = vmail

ssl = required
ssl_cert = <$CERT
ssl_key = <$KEY
ssl_min_protocol = TLSv1.2
ssl_prefer_server_ciphers = yes

disable_plaintext_auth = yes
auth_mechanisms = plain login
auth_username_format = %Lu

passdb {
  driver = passwd-file
  args = scheme=SHA512-CRYPT username_format=%Lu /etc/dovecot/users
}
userdb {
  driver = static
  args = uid=vmail gid=vmail home=/var/mail/vhosts/%d/%n
}

service lmtp {
  unix_listener /var/spool/postfix/private/dovecot-lmtp {
    mode = 0600
    user = postfix
    group = postfix
  }
}
service auth {
  unix_listener /var/spool/postfix/private/auth {
    mode = 0660
    user = postfix
    group = postfix
  }
}

namespace inbox {
  mailbox Drafts {
    special_use = \Drafts
    auto = subscribe
  }
  mailbox Sent {
    special_use = \Sent
    auto = subscribe
  }
  mailbox Junk {
    special_use = \Junk
    auto = subscribe
  }
  mailbox Trash {
    special_use = \Trash
    auto = subscribe
  }
  mailbox Archive {
    special_use = \Archive
    auto = subscribe
  }
}
EOF

# ── OpenDKIM ────────────────────────────────────────────────────────────────
mkdir -p /etc/opendkim/keys/$DOMAIN
if [ ! -f /etc/opendkim/keys/$DOMAIN/$SELECTOR.private ]; then
  opendkim-genkey -b 2048 -d $DOMAIN -D /etc/opendkim/keys/$DOMAIN -s $SELECTOR -v >/dev/null 2>&1
fi
chown -R opendkim:opendkim /etc/opendkim
chmod 700 /etc/opendkim/keys/$DOMAIN
chmod 600 /etc/opendkim/keys/$DOMAIN/$SELECTOR.private
echo "$SELECTOR._domainkey.$DOMAIN $DOMAIN:$SELECTOR:/etc/opendkim/keys/$DOMAIN/$SELECTOR.private" > /etc/opendkim/KeyTable
echo "*@$DOMAIN $SELECTOR._domainkey.$DOMAIN" > /etc/opendkim/SigningTable
printf '127.0.0.1\nlocalhost\n172.16.0.0/12\n' > /etc/opendkim/TrustedHosts
cat > /etc/opendkim.conf <<EOF
Syslog                  yes
UMask                   007
Mode                    sv
Canonicalization        relaxed/simple
OversignHeaders         From
KeyTable                refile:/etc/opendkim/KeyTable
SigningTable            refile:/etc/opendkim/SigningTable
ExternalIgnoreList      refile:/etc/opendkim/TrustedHosts
InternalHosts           refile:/etc/opendkim/TrustedHosts
Socket                  inet:8891@127.0.0.1
PidFile                 /run/opendkim/opendkim.pid
UserID                  opendkim
TrustAnchorFile         /usr/share/dns/root.key
EOF

# ── Postfix ─────────────────────────────────────────────────────────────────
touch /etc/postfix/vmailbox /etc/postfix/virtual /etc/postfix/sender_login
# Служебные адреса — в info@.
for alias in postmaster abuse admin hostmaster webmaster; do
  grep -q "^$alias@$DOMAIN " /etc/postfix/virtual || echo "$alias@$DOMAIN info@$DOMAIN" >> /etc/postfix/virtual
done
postmap /etc/postfix/vmailbox /etc/postfix/virtual /etc/postfix/sender_login

postconf -e \
  "myhostname = $HOST" \
  "mydomain = $DOMAIN" \
  "myorigin = \$mydomain" \
  "mydestination = localhost" \
  "inet_interfaces = all" \
  "inet_protocols = ipv4" \
  "mynetworks = 127.0.0.0/8 172.16.0.0/12" \
  "smtp_address_preference = ipv4" \
  "virtual_mailbox_domains = $DOMAIN" \
  "virtual_mailbox_maps = hash:/etc/postfix/vmailbox" \
  "virtual_alias_maps = hash:/etc/postfix/virtual" \
  "virtual_transport = lmtp:unix:private/dovecot-lmtp" \
  "smtpd_tls_cert_file = $CERT" \
  "smtpd_tls_key_file = $KEY" \
  "smtpd_tls_security_level = may" \
  "smtpd_tls_auth_only = yes" \
  "smtpd_tls_mandatory_protocols = !SSLv2, !SSLv3, !TLSv1, !TLSv1.1" \
  "smtpd_tls_protocols = !SSLv2, !SSLv3, !TLSv1, !TLSv1.1" \
  "smtp_tls_security_level = may" \
  "smtp_tls_loglevel = 1" \
  "smtpd_sasl_type = dovecot" \
  "smtpd_sasl_path = private/auth" \
  "smtpd_sasl_auth_enable = no" \
  "smtpd_helo_required = yes" \
  "disable_vrfy_command = yes" \
  "smtpd_sender_login_maps = hash:/etc/postfix/sender_login" \
  "smtpd_helo_restrictions = permit_mynetworks, reject_invalid_helo_hostname, reject_non_fqdn_helo_hostname" \
  "smtpd_sender_restrictions = permit_mynetworks, reject_non_fqdn_sender, reject_unknown_sender_domain" \
  "smtpd_recipient_restrictions = permit_mynetworks, permit_sasl_authenticated, reject_non_fqdn_recipient, reject_unknown_recipient_domain, reject_unauth_destination" \
  "smtpd_milters = inet:127.0.0.1:8891" \
  "non_smtpd_milters = inet:127.0.0.1:8891" \
  "milter_default_action = accept" \
  "message_size_limit = 26214400" \
  "mailbox_size_limit = 0"

# Отправка из почтовых программ: 587 (STARTTLS) и 465 (TLS), только с паролем
# и только от своего адреса.
postconf -M submission/inet="submission inet n - y - - smtpd"
postconf -P "submission/inet/syslog_name=postfix/submission" \
  "submission/inet/smtpd_tls_security_level=encrypt" \
  "submission/inet/smtpd_sasl_auth_enable=yes" \
  "submission/inet/smtpd_client_restrictions=permit_sasl_authenticated,reject" \
  "submission/inet/smtpd_sender_restrictions=reject_sender_login_mismatch" \
  "submission/inet/smtpd_recipient_restrictions=permit_sasl_authenticated,reject" \
  "submission/inet/milter_macro_daemon_name=ORIGINATING"
postconf -M smtps/inet="smtps inet n - y - - smtpd"
postconf -P "smtps/inet/syslog_name=postfix/smtps" \
  "smtps/inet/smtpd_tls_wrappermode=yes" \
  "smtps/inet/smtpd_sasl_auth_enable=yes" \
  "smtps/inet/smtpd_client_restrictions=permit_sasl_authenticated,reject" \
  "smtps/inet/smtpd_sender_restrictions=reject_sender_login_mismatch" \
  "smtps/inet/smtpd_recipient_restrictions=permit_sasl_authenticated,reject" \
  "smtps/inet/milter_macro_daemon_name=ORIGINATING"

# ── Ящики: добавить / сменить пароль ────────────────────────────────────────
cat > /usr/local/sbin/rentoo-mail-passwd <<'EOF'
#!/bin/bash
# rentoo-mail-passwd [адрес@rentoo.uz] — создать ящик или сменить пароль (спросит дважды).
set -euo pipefail
addr="$(echo "${1:-info@rentoo.uz}" | tr '[:upper:]' '[:lower:]')"
case "$addr" in *@rentoo.uz) ;; *) echo "Только адреса @rentoo.uz" >&2; exit 1;; esac
hash="$(doveadm pw -s SHA512-CRYPT)"
tmp="$(mktemp)"
grep -v "^${addr}:" /etc/dovecot/users > "$tmp" || true
echo "${addr}:${hash}::::::" >> "$tmp"
install -m 640 -o root -g dovecot "$tmp" /etc/dovecot/users
rm -f "$tmp"
grep -q "^${addr} " /etc/postfix/vmailbox || echo "${addr} rentoo.uz/${addr%@*}/" >> /etc/postfix/vmailbox
grep -q "^${addr} " /etc/postfix/sender_login || echo "${addr} ${addr}" >> /etc/postfix/sender_login
postmap /etc/postfix/vmailbox /etc/postfix/sender_login
echo "Готово: ${addr} — пароль сохранён."
EOF
chmod 700 /usr/local/sbin/rentoo-mail-passwd

# Ящик info@ — существует (почта принимается), но войти в него нельзя,
# пока владелец не задаст пароль командой rentoo-mail-passwd.
ADDR=info@$DOMAIN
grep -q "^$ADDR:" /etc/dovecot/users || echo "$ADDR:{SHA512-CRYPT}!locked::::::" >> /etc/dovecot/users
grep -q "^$ADDR " /etc/postfix/vmailbox || echo "$ADDR $DOMAIN/info/" >> /etc/postfix/vmailbox
grep -q "^$ADDR " /etc/postfix/sender_login || echo "$ADDR $ADDR" >> /etc/postfix/sender_login
postmap /etc/postfix/vmailbox /etc/postfix/sender_login

systemctl enable -q opendkim dovecot postfix
systemctl restart opendkim dovecot postfix
postfix check
echo "--- listening"
ss -ltn | grep -E ":(25|465|587|993|8891) " | awk '{print $4}'
echo "--- DKIM"
cat /etc/opendkim/keys/$DOMAIN/$SELECTOR.txt
