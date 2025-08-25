## GitHub CLI setting
### Install GitHub CLI(https://github.com/cli/cli/blob/trunk/docs/install_linux.md)
```
(type -p wget >/dev/null || (sudo apt update && sudo apt-get install wget -y)) \
	&& sudo mkdir -p -m 755 /etc/apt/keyrings \
        && out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        && cat $out | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
	&& sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
	&& echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
	&& sudo apt update \
	&& sudo apt install gh -y
```
```
apt update
apt install zip -y
apt install gh
```
### GH_TOKEN setting
```
vi ~/.bashrc
```
add
```
export GH_TOKEN=$YOUR_TOKEN
```
to the end.

You can clone this repository using
```
git clone https://$GH_TOKEN@github.com/railabatkaist/raisin_master.git
```
The token lasts for 1 year, so you will need to update it every year.

## How to update the software version
To change the software version(for example, to v0.0.0),
```
cd $RAISIN_WS
git checkout main
git checkout v0.0.0
bash precompiled/raisin/download_precompiled_raisin.sh
python3 raisin_workspace_setup.py
```

## Tutorials
### Raisin master basics
https://youtu.be/zUZwiI6xp6U?si=tJ7LRPgwGcZIr7xZ

### How to make a custom Raisin gui window
https://youtu.be/EDxzJGgsrDU

### Raisin lock profiler
https://youtu.be/MT73AlW7Wag

### raisin documentation
https://raionrobotics.com/documentation
