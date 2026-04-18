/**
 * CommonCreed Remotion sidecar — HTTP server.
 *
 * Exposes two endpoints:
 *
 *   POST /render
 *     body: {
 *       template_id: "bar_chart" | "number_ticker" | "line_chart",
 *       props: object,
 *       audio_url: string | null,
 *       target_duration_s: number,
 *     }
 *     200: { output_path, render_time_ms, duration_in_frames, fps, width, height }
 *     400: { error } — invalid spec
 *     500: { error } — render failure
 *
 *   GET /healthz
 *     200: { ok: true }
 *
 * The server runs as PID 1 inside the commoncreed_remotion container. Outputs
 * are written under /app/output/<timestamp>/cinematic_chart.mp4 on the shared
 * `commoncreed_output` volume so the Python sidecar can pick them up.
 */
import { promises as fs } from "node:fs";
import path from "node:path";
import process from "node:process";

import express, { type Request, type Response } from "express";

import {
  renderTemplate,
  getBundle,
  TEMPLATE_IDS,
  type TemplateId,
  type RenderInput,
} from "./render.js";

const PORT = Number(process.env.REMOTION_PORT ?? 3030);
const OUTPUT_ROOT = process.env.REMOTION_OUTPUT_ROOT ?? "/app/output";
const OUTPUT_FILENAME = "cinematic_chart.mp4";
/** Body size cap for /render. Props are small; a generous cap still blocks abuse. */
const BODY_LIMIT_BYTES = 1 * 1024 * 1024; // 1 MB

interface RenderRequestBody {
  template_id: TemplateId;
  props: Record<string, unknown>;
  audio_url: string | null;
  target_duration_s: number;
}

interface ValidationResult<T> {
  ok: true;
  value: T;
}
interface ValidationError {
  ok: false;
  error: string;
}

/**
 * Lightweight hand-rolled validator. We deliberately avoid Zod or Joi to keep
 * the container small; the payload shape is tiny and stable.
 */
function validateRenderBody(
  raw: unknown,
): ValidationResult<RenderRequestBody> | ValidationError {
  if (raw === null || typeof raw !== "object") {
    return { ok: false, error: "body must be a JSON object" };
  }
  const body = raw as Record<string, unknown>;

  const templateId = body.template_id;
  if (typeof templateId !== "string") {
    return { ok: false, error: "template_id must be a string" };
  }
  if (!TEMPLATE_IDS.includes(templateId as TemplateId)) {
    return {
      ok: false,
      error: `template_id must be one of ${TEMPLATE_IDS.join(", ")}`,
    };
  }

  const props = body.props;
  if (props === null || typeof props !== "object" || Array.isArray(props)) {
    return { ok: false, error: "props must be a JSON object" };
  }

  const audioUrlRaw = body.audio_url ?? null;
  if (audioUrlRaw !== null && typeof audioUrlRaw !== "string") {
    return { ok: false, error: "audio_url must be a string or null" };
  }

  const targetDurationS = body.target_duration_s;
  if (
    typeof targetDurationS !== "number" ||
    !Number.isFinite(targetDurationS) ||
    targetDurationS <= 0
  ) {
    return {
      ok: false,
      error: "target_duration_s must be a positive finite number",
    };
  }
  if (targetDurationS > 120) {
    return { ok: false, error: "target_duration_s must be <= 120" };
  }

  return {
    ok: true,
    value: {
      template_id: templateId as TemplateId,
      props: props as Record<string, unknown>,
      audio_url: audioUrlRaw,
      target_duration_s: targetDurationS,
    },
  };
}

/**
 * Build the output path: /app/output/<timestamp>/cinematic_chart.mp4.
 * The timestamp is milliseconds since epoch to avoid collisions across
 * concurrent renders in the same second.
 */
async function allocateOutputPath(): Promise<string> {
  const stamp = Date.now().toString();
  const dir = path.join(OUTPUT_ROOT, stamp);
  await fs.mkdir(dir, { recursive: true });
  return path.join(dir, OUTPUT_FILENAME);
}

async function handleRender(req: Request, res: Response): Promise<void> {
  const validation = validateRenderBody(req.body);
  if (!validation.ok) {
    res.status(400).json({ error: validation.error });
    return;
  }
  const { template_id, props, audio_url, target_duration_s } = validation.value;

  const started = Date.now();
  let outputPath: string;
  try {
    outputPath = await allocateOutputPath();
  } catch (err) {
    res.status(500).json({
      error: `could not allocate output directory: ${(err as Error).message}`,
    });
    return;
  }

  const input: RenderInput = {
    templateId: template_id,
    props,
    targetDurationS: target_duration_s,
    outputPath,
    audioTrackUrl: audio_url,
  };

  try {
    const result = await renderTemplate(input);
    const elapsed = Date.now() - started;
    res.status(200).json({
      output_path: result.outputPath,
      render_time_ms: elapsed,
      duration_in_frames: result.durationInFrames,
      fps: result.fps,
      width: result.width,
      height: result.height,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    // eslint-disable-next-line no-console -- deliberate: container stderr is our only log sink
    console.error(`[render] template=${template_id} failed: ${message}`);
    res.status(500).json({ error: `render failed: ${message}` });
  }
}

function handleHealth(_req: Request, res: Response): void {
  res.status(200).json({ ok: true });
}

export function createApp(): express.Express {
  const app = express();
  app.use(express.json({ limit: BODY_LIMIT_BYTES }));
  app.get("/healthz", handleHealth);
  app.post("/render", (req, res) => {
    void handleRender(req, res);
  });
  // Explicit 404 JSON so misrouted clients get a predictable response.
  app.use((_req, res) => {
    res.status(404).json({ error: "not found" });
  });
  return app;
}

async function main(): Promise<void> {
  // Ensure the output root exists before we start accepting requests.
  await fs.mkdir(OUTPUT_ROOT, { recursive: true });

  // Warm the Remotion bundle so the first /render isn't delayed by webpack.
  // Failures here are fatal: a broken bundle means every render will fail.
  // eslint-disable-next-line no-console
  console.log("[startup] bundling Remotion entry point...");
  try {
    await getBundle();
    // eslint-disable-next-line no-console
    console.log("[startup] bundle ready");
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    // eslint-disable-next-line no-console
    console.error(`[startup] bundle failed: ${message}`);
    process.exitCode = 1;
    throw err;
  }

  const app = createApp();
  app.listen(PORT, () => {
    // eslint-disable-next-line no-console
    console.log(`[startup] remotion sidecar listening on :${PORT}`);
  });
}

// Entry point when run as `node dist/server.js`.
void main().catch((err) => {
  const message = err instanceof Error ? err.message : String(err);
  // eslint-disable-next-line no-console
  console.error(`[fatal] ${message}`);
  process.exit(1);
});
