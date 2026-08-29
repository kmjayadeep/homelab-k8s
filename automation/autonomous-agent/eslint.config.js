import eslint from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  { ignores: ["dist/**", "node_modules/**"] },
  { files: ["**/*.ts"], languageOptions: { parserOptions: { project: "./tsconfig.json" } }, rules: { "@typescript-eslint/no-non-null-assertion": "off" } },
);
