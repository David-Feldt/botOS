#!/bin/bash
set -e

INSTALL_DIR="/opt/bot"
BIN="/usr/local/bin/bot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing botOS to $INSTALL_DIR..."

sudo mkdir -p "$INSTALL_DIR/src/vendor"

echo "  copying source files..."
sudo cp -r "$SCRIPT_DIR/src/." "$INSTALL_DIR/src/"
sudo cp "$SCRIPT_DIR/bot" "$INSTALL_DIR/bot"
sudo chmod +x "$INSTALL_DIR/bot"

echo "  vendoring PyYAML..."
TMP=$(mktemp -d)
curl -fsSL "https://files.pythonhosted.org/packages/source/P/PyYAML/PyYAML-6.0.1.tar.gz" \
    | tar -xz -C "$TMP"
sudo cp -r "$TMP"/PyYAML-*/lib/yaml "$INSTALL_DIR/src/vendor/"
rm -rf "$TMP"

echo "  installing shell setup..."
sudo cp "$SCRIPT_DIR/setup.sh" "$INSTALL_DIR/setup.sh"
if ! grep -q "bot/setup.sh" ~/.bashrc 2>/dev/null; then
    echo "source $INSTALL_DIR/setup.sh" >> ~/.bashrc
fi

echo "  linking bot -> $BIN"
sudo ln -sf "$INSTALL_DIR/bot" "$BIN"

echo ""
echo "Done. Run 'bot init <name>' to create a new project."
echo "Restart your shell or run: source $INSTALL_DIR/setup.sh"
