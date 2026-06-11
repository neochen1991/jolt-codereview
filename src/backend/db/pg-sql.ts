export type SqlParams = Array<string | number | boolean | null | Buffer>;

export function splitSqlStatements(sql: string): string[] {
  const statements: string[] = [];
  let current = "";
  let inSingleQuote = false;
  let inDoubleQuote = false;
  for (let index = 0; index < sql.length; index += 1) {
    const char = sql[index];
    const next = sql[index + 1];
    if (char === "'" && !inDoubleQuote) {
      current += char;
      if (inSingleQuote && next === "'") {
        current += next;
        index += 1;
      } else {
        inSingleQuote = !inSingleQuote;
      }
      continue;
    }
    if (char === '"' && !inSingleQuote) {
      current += char;
      inDoubleQuote = !inDoubleQuote;
      continue;
    }
    if (char === ";" && !inSingleQuote && !inDoubleQuote) {
      const trimmed = current.trim();
      if (trimmed) statements.push(trimmed);
      current = "";
      continue;
    }
    current += char;
  }
  const trimmed = current.trim();
  if (trimmed) statements.push(trimmed);
  return statements;
}

export function translateSqliteToPostgres(sql: string) {
  let translated = sql.trim().replace(/;+\s*$/g, "");
  translated = translated.replace(/BEGIN\s+IMMEDIATE/gi, "BEGIN");
  translated = translated.replace(/datetime\(\s*'now'\s*,\s*\?\s*\)/gi, "(CURRENT_TIMESTAMP + ?::interval)");
  translated = translated.replace(/datetime\(\s*'now'\s*,\s*'([^']+)'\s*\)/gi, "(CURRENT_TIMESTAMP + INTERVAL '$1')");
  translated = translated.replace(/datetime\(\s*'now'\s*\)/gi, "CURRENT_TIMESTAMP");
  translated = translated.replace(/lower\s*\(\s*hex\s*\(\s*randomblob\s*\(\s*(\d+)\s*\)\s*\)\s*\)/gi, (_match, size) => {
    const hexLength = Math.max(1, Number(size) * 2);
    return `substr(md5(random()::text || clock_timestamp()::text), 1, ${hexLength})`;
  });
  translated = translated.replace(/^INSERT\s+OR\s+IGNORE\s+INTO\s+/i, "INSERT INTO ");
  if (/^INSERT\s+INTO\s+/i.test(translated) && !/\bON\s+CONFLICT\b/i.test(translated)) {
    translated = `${translated} ON CONFLICT DO NOTHING`;
  }
  translated = replacePlaceholders(translated);
  return translated;
}

function replacePlaceholders(sql: string) {
  let output = "";
  let index = 1;
  let inSingleQuote = false;
  let inDoubleQuote = false;
  for (let position = 0; position < sql.length; position += 1) {
    const char = sql[position];
    const next = sql[position + 1];
    if (char === "'" && !inDoubleQuote) {
      output += char;
      if (inSingleQuote && next === "'") {
        output += next;
        position += 1;
      } else {
        inSingleQuote = !inSingleQuote;
      }
      continue;
    }
    if (char === '"' && !inSingleQuote) {
      output += char;
      inDoubleQuote = !inDoubleQuote;
      continue;
    }
    if (char === "?" && !inSingleQuote && !inDoubleQuote) {
      output += `$${index}`;
      index += 1;
      continue;
    }
    output += char;
  }
  return output;
}
