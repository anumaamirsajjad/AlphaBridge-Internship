#!/bin/sh
# Applies the migrations in /flyway/sql to the database named in DATABASE_URL.
# DATABASE_URL has the form postgres://user:password@host:port/dbname[?options].
# The user and password must not contain '@', ':' or '/', because they are not URL-decoded here.
# Prints nothing from DATABASE_URL, so the password stays out of the logs.
set -eu

: "${DATABASE_URL:?DATABASE_URL is not set}"

rest="${DATABASE_URL#*://}"
userpass="${rest%%@*}"
hostpath="${rest#*@}"

user="${userpass%%:*}"
password="${userpass#*:}"
hostport="${hostpath%%/*}"
dbpath="${hostpath#*/}"
dbname="${dbpath%%\?*}"

query=""
case "$dbpath" in
    *\?*) query="?${dbpath#*\?}" ;;
esac

export FLYWAY_URL="jdbc:postgresql://${hostport}/${dbname}${query}"
export FLYWAY_USER="$user"
export FLYWAY_PASSWORD="$password"

# Runs "migrate" unless another Flyway command is given, for example: baseline -baselineVersion=3
if [ $# -eq 0 ]; then
    set -- migrate
fi

exec /flyway/flyway -connectRetries=3 "$@"
