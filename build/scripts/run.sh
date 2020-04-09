#!/bin/bash

function help() {
  echo "
    Usage: $(basename $0) [OPTIONS]

    Options:
      -d <database>                Database (mysql | pgsql | sqlite) (default: sqlite)
      -h                           Help
      -p <path>                    Path to folder (default: current folder \$PWD)
      -r                           Reload Database
  "
  exit 0
}

function run() {
  if [[ -n "$path" ]]; then cd $path; fi
  if [ "$scheduler" = true ]; then
    cd scheduler
    export ENMS_ADDRESS="http://192.168.56.102:5000"
    uvicorn scheduler:scheduler --host 0.0.0.0
    exit 0
  fi
  export FLASK_APP="app.py"
  export FLASK_DEBUG=1
  if [ "$database" = "mysql" ]; then
    export DATABASE_URL="mysql://root:password@localhost/enms";
  elif [ "$database" = "pgsql" ]; then
    export DATABASE_URL="postgresql://root:password@localhost:5432/enms"
  else
    export DATABASE_URL="sqlite:///database.db"
  fi
  if [ "$reload" = true ]; then
    if [ "$database" = "mysql" ]; then
      sudo mysql -u root --password=password -e "DROP DATABASE enms;CREATE DATABASE enms;"
    elif [ "$database" = "pgsql" ]; then
      sudo -u postgres psql -c "DROP DATABASE enms"
      sudo -u postgres psql -c "CREATE DATABASE enms;"
    else
      rm database.db
    fi
  fi
  if [ "$gunicorn" = true ]; then
    gunicorn --config gunicorn.py app:app
  else
    flask run -h 0.0.0.0
  fi
}

while getopts h?grsvp:d: opt; do
    case "$opt" in
      d) database=$OPTARG;;
      g) gunicorn=true;;
      p) path=$OPTARG;;
      r) reload=true;;
      s) scheduler=true;;
      h|\?) help;;
    esac
done

run