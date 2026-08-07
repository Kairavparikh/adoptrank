const vscode = require("vscode");

function run(query) {
  const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (!root) return vscode.window.showErrorMessage("Open a workspace before running AdoptRank.");
  const api = vscode.workspace.getConfiguration("adoptrank").get("apiUrl");
  const terminal = vscode.window.createTerminal({ name: "AdoptRank", cwd: root });
  const safeQuery = query.replaceAll("'", "'\\''");
  terminal.sendText(`adoptrank-backend find '${safeQuery}' --path . --api '${api}'`);
  terminal.show();
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
}

function deactivate() {}
module.exports = { activate, deactivate };
