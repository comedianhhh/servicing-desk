import { OPERATOR_NAMES } from "@/lib/operators";

// Names only — tokens stay on the server.
export function GET() {
  return Response.json(OPERATOR_NAMES);
}
