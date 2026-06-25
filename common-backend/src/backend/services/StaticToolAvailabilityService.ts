import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

type ToolSpec = {
  name: string;
  displayName: string;
  category: string;
  requiredFor: string;
  versionArgs: string[];
  installHint: string;
  check?: "executable" | "python-module";
  modules?: string[];
};

const TOOL_SPECS: ToolSpec[] = [
  {
    name: "tree-sitter",
    displayName: "Tree-sitter",
    category: "Code Graph",
    requiredFor: "Java/Spring 语法图谱、调用关系、影响范围上下文",
    versionArgs: [],
    installHint: "项目依赖：pip install tree_sitter tree_sitter_java tree_sitter_python tree_sitter_javascript tree_sitter_typescript",
    check: "python-module",
    modules: ["tree_sitter", "tree_sitter_java", "tree_sitter_python", "tree_sitter_javascript", "tree_sitter_typescript"]
  },
  { name: "semgrep", displayName: "Semgrep", category: "SAST", requiredFor: "Java/Spring 规则、通用安全规则", versionArgs: ["--version"], installHint: "macOS/Linux: pipx install semgrep；Windows: pipx install semgrep" },
  { name: "gitleaks", displayName: "Gitleaks", category: "Secret", requiredFor: "密钥泄露扫描", versionArgs: ["version"], installHint: "macOS: brew install gitleaks；Windows: winget install Gitleaks.Gitleaks 或下载 release" },
  { name: "ruff", displayName: "Ruff", category: "Python", requiredFor: "Python 静态检查", versionArgs: ["--version"], installHint: "pip install ruff" },
  { name: "bandit", displayName: "Bandit", category: "Python Security", requiredFor: "Python 安全扫描", versionArgs: ["--version"], installHint: "pip install bandit" },
  { name: "eslint", displayName: "ESLint", category: "Frontend", requiredFor: "JS/TS 静态检查", versionArgs: ["--version"], installHint: "npm install -g eslint" },
  { name: "pmd", displayName: "PMD", category: "Java Source", requiredFor: "Java 规范、复杂度、安全规则", versionArgs: ["--version"], installHint: "macOS: brew install pmd；Windows: 下载 PMD 并把 bin 加入 PATH" },
  { name: "checkstyle", displayName: "Checkstyle", category: "Java Style", requiredFor: "Java 基础规范", versionArgs: ["--version"], installHint: "macOS: brew install checkstyle；Windows: 下载 jar 后配置 checkstyle.cmd" },
  { name: "spotbugs", displayName: "SpotBugs", category: "Java Bytecode", requiredFor: "字节码缺陷、FindSecBugs 安全规则", versionArgs: ["-version"], installHint: "macOS: brew install spotbugs；Windows: 下载 SpotBugs 并把 bin 加入 PATH" },
  { name: "dependency-check", displayName: "OWASP Dependency-Check", category: "Dependency", requiredFor: "依赖 CVE 扫描", versionArgs: ["--version"], installHint: "macOS: brew install dependency-check；Windows: 下载 Dependency-Check CLI 并加入 PATH" },
  { name: "osv-scanner", displayName: "OSV Scanner", category: "Dependency", requiredFor: "OSV 依赖漏洞扫描", versionArgs: ["--version"], installHint: "macOS: brew install osv-scanner；Windows: winget install Google.OSV-Scanner 或下载 release" },
  { name: "trivy", displayName: "Trivy", category: "Container/IaC", requiredFor: "依赖、镜像、配置、密钥扫描", versionArgs: ["--version"], installHint: "macOS: brew install trivy；Windows: winget install AquaSecurity.Trivy" },
  { name: "kics", displayName: "KICS", category: "IaC", requiredFor: "K8s、Docker、Terraform 配置风险", versionArgs: ["version"], installHint: "macOS/Linux/Windows: 下载 KICS release 并加入 PATH" },
  { name: "openapi-diff", displayName: "OpenAPI Diff", category: "API", requiredFor: "OpenAPI 破坏性变更检测", versionArgs: ["--version"], installHint: "npm install -g openapi-diff 或配置兼容 CLI" }
];

function windowsExecutableCandidates(command: string) {
  const pathext = (process.env.PATHEXT || ".EXE;.CMD;.BAT;.COM;.PS1")
    .split(";")
    .filter(Boolean);
  const hasExt = Boolean(path.extname(command));
  return hasExt ? [command] : [command, ...pathext.map((ext) => `${command}${ext.toLowerCase()}`), ...pathext.map((ext) => `${command}${ext.toUpperCase()}`)];
}

function resolveExecutable(command: string) {
  const pathEnv = process.env.PATH || "";
  const pathParts = pathEnv.split(path.delimiter).filter(Boolean);
  const candidates = process.platform === "win32" ? windowsExecutableCandidates(command) : [command];
  for (const dir of pathParts) {
    for (const candidate of candidates) {
      const fullPath = path.join(dir, candidate);
      try {
        if (fs.existsSync(fullPath) && fs.statSync(fullPath).isFile()) return fullPath;
      } catch {
        // Ignore unreadable PATH entries.
      }
    }
  }
  return null;
}

function readVersion(executablePath: string, args: string[]) {
  const completed = spawnSync(executablePath, args, {
    encoding: "utf-8",
    timeout: 5000,
    windowsHide: true
  });
  const output = `${completed.stdout || ""}${completed.stderr || ""}`.trim();
  return {
    status: completed.error ? "version_failed" : "available",
    version: summarizeVersion(output),
    return_code: completed.status
  };
}

function summarizeVersion(output: string) {
  const cleanedLines = output
    .replace(/\u001b\[[0-9;]*m/g, "")
    .split(/\r?\n/)
    .map((line) => line.replace(/[█]+/g, "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
  const versionLike = cleanedLines.find((line) => /\b(version|v?\d+\.\d+|PMD)\b/i.test(line));
  return (versionLike || cleanedLines[0] || "available").slice(0, 160);
}

function projectPythonCandidates() {
  const cwd = process.cwd();
  return process.platform === "win32"
    ? [path.join(cwd, ".venv", "Scripts", "python.exe"), "python", "py"]
    : [path.join(cwd, ".venv", "bin", "python"), "python3", "python"];
}

function readPythonModules(modules: string[]) {
  const script = [
    "import importlib.util, json",
    `mods=${JSON.stringify(modules)}`,
    "status={m: bool(importlib.util.find_spec(m)) for m in mods}",
    "print(json.dumps(status))"
  ].join("; ");
  for (const candidate of projectPythonCandidates()) {
    const executable = path.isAbsolute(candidate) ? candidate : resolveExecutable(candidate);
    if (!executable || !fs.existsSync(executable)) continue;
    const completed = spawnSync(executable, ["-c", script], {
      encoding: "utf-8",
      timeout: 5000,
      windowsHide: true
    });
    if (completed.error || completed.status !== 0) continue;
    try {
      const status = JSON.parse(completed.stdout || "{}") as Record<string, boolean>;
      const missing = modules.filter((moduleName) => !status[moduleName]);
      return {
        available: missing.length === 0,
        status: missing.length ? "missing_modules" : "available",
        path: executable,
        version: missing.length ? `missing: ${missing.join(", ")}` : `${modules.length} modules available`,
        return_code: completed.status
      };
    } catch {
      // Continue with the next candidate.
    }
  }
  return {
    available: false,
    status: "missing_python",
    path: null,
    version: null,
    return_code: null
  };
}

export class StaticToolAvailabilityService {
  listAvailability() {
    const items = TOOL_SPECS.map((tool) => {
      if (tool.check === "python-module") {
        const version = readPythonModules(tool.modules || []);
        return {
          ...tool,
          ...version
        };
      }
      const executablePath = resolveExecutable(tool.name);
      if (!executablePath) {
        return {
          ...tool,
          available: false,
          status: "missing",
          path: null,
          version: null,
          return_code: null
        };
      }
      const version = readVersion(executablePath, tool.versionArgs);
      return {
        ...tool,
        available: true,
        status: version.status,
        path: executablePath,
        version: version.version,
        return_code: version.return_code
      };
    });
    const availableCount = items.filter((item) => item.available).length;
    return {
      platform: process.platform,
      os: `${os.type()} ${os.release()}`,
      path_delimiter: path.delimiter,
      checked_at: new Date().toISOString(),
      total: items.length,
      available_count: availableCount,
      missing_count: items.length - availableCount,
      items
    };
  }
}
