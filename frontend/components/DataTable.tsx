import type { TableFrame } from "@/lib/frames";

/** Query result table. Values render as text nodes, so no HTML injection. */
export default function DataTable({ table }: { table: TableFrame }) {
  if (!table.rows.length) {
    return <p className="text-sm text-slate-400">No rows matched.</p>;
  }
  return (
    <div className="max-h-80 overflow-auto rounded-lg border border-slate-800">
      <table className="w-full border-collapse text-left text-sm">
        <thead className="sticky top-0 bg-slate-900">
          <tr>
            {table.columns.map((column) => (
              <th
                key={column}
                scope="col"
                className="border-b border-slate-800 px-3 py-2 font-semibold text-slate-300"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="odd:bg-slate-950/40">
              {row.map((cell, cellIndex) => (
                <td
                  key={cellIndex}
                  className="border-b border-slate-800/60 px-3 py-2 text-slate-200"
                >
                  {cell === null ? "—" : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
