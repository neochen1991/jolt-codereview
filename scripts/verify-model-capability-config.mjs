import fs from "node:fs";
import path from "node:path";


const root = process.cwd();
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");
const requireText = (relative, needle) => {
  const content = read(relative);
  if (!content.includes(needle)) {
    throw new Error(`${relative} missing ${JSON.stringify(needle)}`);
  }
};

requireText("frontend/src/frontend/shared.ts", "Math.min(131072, parsed)");
requireText("frontend/src/frontend/components/ConfigViews.tsx", 'max="131072"');
requireText("frontend/src/frontend/components/ProjectViews.tsx", 'max="131072"');
requireText("common-backend/config.example.json", '"model_overrides"');
requireText("common-backend/config.example.json", '"glm-5.2"');
requireText("common-backend/config.example.json", '"MiniMax-M2.7"');
requireText("common-backend/src/backend/routes/models.routes.ts", "model_overrides: input.model_overrides");
requireText("common-backend/src/backend/types.ts", "model_overrides?:");
requireText("mr-backend/src/backend/types.ts", "model_overrides?:");
requireText("README.md", "GLM-5.2");
requireText("README.md", "MiniMax-M2.7");
requireText("README.md", "model_overrides");

console.log("model capability config verification passed");
