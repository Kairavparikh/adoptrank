const vscode = require("vscode");

function run(query) {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (!root) return vscode.window.showErrorMessage("Open a workspace before running AdoptRank.");
  const api = vscode.workspace.getConfiguration("adoptrank").get("apiUrl");
  const terminal = vscode.window.createTerminal({ name: "AdoptRank", cwd: root });
  const safeQuery = query.replaceAll("'", "'\\''");
  terminal.sendText(`adoptrank find '${safeQuery}' --path . --api '${api}'`);
  terminal.show();
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", "'\\''")}'`;
}

function activate(context) {
  context.subscriptions.push(vscode.commands.registerCommand("adoptrank.find", async () => {
    const query = await vscode.window.showInputBox({ prompt: "What repository capability do you need?" });
    if (query) run(query);
  }));
  context.subscriptions.push(vscode.commands.registerCommand("adoptrank.findSelection", async () => {
    const selection = vscode.window.activeTextEditor?.document.getText(vscode.window.activeTextEditor.selection).trim();
    const query = selection || await vscode.window.showInputBox({ prompt: "Describe the capability" });
    if (query) run(query);
  }));
  context.subscriptions.push(vscode.commands.registerCommand("adoptrank.leaderboard", async () => {
    const owner = await vscode.window.showInputBox({
      prompt: "Optional GitHub username or organization (leave blank for overall)",
      placeHolder: "openai",
    });
    if (owner === undefined) return;
    const webUrl = vscode.workspace.getConfiguration("adoptrank").get("webUrl");
    const terminal = vscode.window.createTerminal({ name: "AdoptRank Leaderboard" });
    const ownerFlag = owner.trim() ? ` --owner ${shellQuote(owner.trim())}` : "";
    terminal.sendText(`adoptrank leaderboard${ownerFlag} --api ${shellQuote(webUrl)}`);
    terminal.show();
  }));
}

function deactivate() {}
module.exports = { activate, deactivate };
