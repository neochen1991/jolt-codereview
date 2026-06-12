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
  if (/^(CREATE|ALTER)\b/i.test(translated)) {
    translated = translateSqliteSchemaToPostgres(translated);
  }
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
  translated = castTextTimestampComparisons(translated);
  return translated;
}

export function translateSqliteSchemaToPostgres(sql: string) {
  return sql
    .replace(/"([^"]+)"/g, '"$1"')
    .replace(/\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b/gi, "SERIAL PRIMARY KEY")
    .replace(/\bDATETIME\b(?!\s*\()/gi, "TEXT")
    .replace(/\bBOOLEAN\b/gi, "INTEGER")
    .replace(/\b(TEXT(?:\s+NOT\s+NULL)?\s+DEFAULT\s+)CURRENT_TIMESTAMP\b/gi, "$1(CURRENT_TIMESTAMP::text)");
}

export function castTextTimestampComparisons(sql: string) {
  const timestampColumn = String.raw`(?:[A-Za-z_][A-Za-z0-9_]*\.)?[A-Za-z_][A-Za-z0-9_]*_at`;
  const timestampCoalesce = String.raw`COALESCE\s*\(\s*(?:${timestampColumn}\s*,\s*)+${timestampColumn}\s*\)`;
  const timestampExpression = String.raw`(?:CURRENT_TIMESTAMP|\(CURRENT_TIMESTAMP\s*\+\s*(?:INTERVAL\s+'[^']+'|\$\d+::interval|%s::interval)\))`;
  let translated = sql.replace(
    new RegExp(`\\b(${timestampCoalesce})\\s*(<=|>=|<|>)\\s*(${timestampExpression})`, "gi"),
    (_match, columnExpression: string, operator: string, rightExpression: string) =>
      `${castTimestampOperand(columnExpression)} ${operator} ${rightExpression}`
  );
  translated = translated.replace(
    new RegExp(`\\b(${timestampColumn})\\s*(<=|>=|<|>)\\s*(${timestampExpression})`, "gi"),
    (_match, columnExpression: string, operator: string, rightExpression: string) =>
      `${castTimestampOperand(columnExpression)} ${operator} ${rightExpression}`
  );
  translated = translated.replace(
    new RegExp(`(${timestampExpression})\\s*(<=|>=|<|>)\\s*\\b(${timestampCoalesce})`, "gi"),
    (_match, leftExpression: string, operator: string, columnExpression: string) =>
      `${leftExpression} ${operator} ${castTimestampOperand(columnExpression)}`
  );
  translated = translated.replace(
    new RegExp(`(${timestampExpression})\\s*(<=|>=|<|>)\\s*\\b(${timestampColumn})`, "gi"),
    (_match, leftExpression: string, operator: string, columnExpression: string) =>
      `${leftExpression} ${operator} ${castTimestampOperand(columnExpression)}`
  );
  return translated;
}

function castTimestampOperand(operand: string) {
  if (/::timestamptz\b/i.test(operand)) return operand;
  if (/^COALESCE\s*\(/i.test(operand)) return `NULLIF(${operand}, '')::timestamptz`;
  return `NULLIF(${operand}, '')::timestamptz`;
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
