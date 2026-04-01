# botOS shell setup — sourced automatically via .bashrc
# Usage: bot .   (re-source this file)

pip() {
    if [ "$1" = "install" ] && [ -f "config.yaml" ] && grep -q "^components:" config.yaml 2>/dev/null; then
        echo "You're in a botOS project."
        read -rp "Install to this project's environment? [Y/n] " ans
        if [ -z "$ans" ] || [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
            if [ ! -d ".botos/venv" ]; then
                echo "Creating project environment..."
                python3 -m venv .botos/venv
            fi
            .botos/venv/bin/pip "$@"
            return
        fi
    fi
    command pip "$@"
}

pip3() { pip "$@"; }

bot() {
    if [ "$1" = "." ]; then
        source /opt/bot/setup.sh
        echo "Shell setup loaded."
        return
    fi
    command bot "$@"
}

if [ -z "$BOTOS_SHELL_SETUP" ]; then
    PS1="(bot) $PS1"
fi
export BOTOS_SHELL_SETUP=1
