// The monode #67 request-log record, copied from bioc-edge
// (worker/src/keys.ts accessRecord) per the standard: copied into the site,
// not a shared package. #67 specifies a Hono middleware; this Worker is not
// Hono, so it is a plain function that index.ts calls once per request and
// console.logs as one JSON line (`logpush = true` ships it).
// Keep `v` and the field set in step with bioc-edge; the schema is #67's.

/**
 * Wire bytes, where we can know them without changing what we send.
 *
 * Deliberately does not set Content-Length anywhere to make this easier: the
 * zone compresses text/html at the edge, downstream of us, so a length we
 * derived here would be wrong on exactly the responses it is hardest to notice
 * on. Unknown is recorded as null rather than guessed -- a fabricated zero
 * would silently understate transfer volume forever.
 */
function bytesOf(res: Response | null, size: number | null): number | null {
  if (!res) return null;
  const len = res.headers.get("content-length");
  if (len) return Number(len);
  const r = rangeOf(res);
  if (r) return r.end - r.start + 1;
  // A streamed R2 body carries no Content-Length, so a full 200 GET -- every
  // tarball download, i.e. the thing the statistics are actually about -- would
  // otherwise record null forever. The object size is the body length for that
  // case and only that case: a HEAD sends no body, and anything else either
  // set a length above or genuinely has none.
  if (size !== null && res.status === 200 && res.body !== null) return size;
  return null;
}

/** `Content-Range: bytes 0-99/1234` -> the CloudFront sc_range_start/end pair. */
export function rangeOf(res: Response | null): { start: number; end: number } | null {
  const m = /^bytes (\d+)-(\d+)\//.exec(res?.headers.get("content-range") ?? "");
  return m ? { start: Number(m[1]), end: Number(m[2]) } : null;
}

/**
 * The record, as a plain object so it can be asserted on.
 *
 * Field names are CloudFront's, verbatim, from FIELDS in
 * cloudfront-logs-to-parquet.py. Calibrating the two series across the cutover
 * overlap is then a column-for-column comparison rather than a mapping
 * exercise -- and the mapping is the part that would rot.
 *
 * `null` means "this edge cannot know it", never zero. A fabricated zero in
 * sc_bytes or time_taken would understate transfer and latency forever, and
 * would look like real data while doing it.
 */
function logCf(cf: Record<string, unknown>): Record<string, unknown> {
  const { tlsExportedAuthenticator, tlsClientRandom, tlsClientAuth, ...kept } = cf;
  return kept;
}

export function accessRecord(
  req: Request,
  status: number,
  cacheStatus: string,
  res: Response | null,
  t0: number | null,
  size: number | null = null,
) {
  const cf = req.cf as IncomingRequestCfProperties | undefined;
  const url = new URL(req.url);
  const now = Date.now();
  const contentRange = rangeOf(res);
  return {
      type: "access",
      v: 1,

      // date and time are deliberately not split out: they are derivable from
      // ts, and splitting here would be a derived column at ingest (bioc-edge ADR 0002).
      ts: now,
      x_edge_location: cf?.colo ?? null,
      // Body bytes. CloudFront counts headers too, so this runs slightly low
      // against sc_bytes -- a known, constant-ish offset rather than a gap.
      sc_bytes: bytesOf(res, size),
      c_ip: req.headers.get("cf-connecting-ip"),
      cs_method: req.method,
      cs_host: url.host,
      cs_uri_stem: url.pathname,
      sc_status: status,
      cs_referer: req.headers.get("referer"),
      cs_user_agent: req.headers.get("user-agent"),
      cs_uri_query: url.search,
      // Deliberately not collected. CloudFront logs cookies, but this is a
      // static site that sets none, and starting to retain them would put
      // third-party tokens into a permanent archive for no analytical gain.
      // Collection is a separate act from filtering a copy -- see bioc-edge#69.
      cs_cookie: null,
      x_edge_result_type: cacheStatus,
      x_edge_request_id: req.headers.get("cf-ray"),
      x_host_header: req.headers.get("host"),
      cs_protocol: url.protocol.replace(":", ""),
      // Request bytes are not exposed to a Worker.
      cs_bytes: null,
      time_taken: t0 === null ? null : now - t0,
      x_forwarded_for: req.headers.get("x-forwarded-for"),
      ssl_protocol: cf?.tlsVersion ?? null,
      ssl_cipher: cf?.tlsCipher ?? null,
      x_edge_response_result_type: cacheStatus,
      cs_protocol_version: cf?.httpProtocol ?? null,
      // CloudFront field-level encryption. No analogue, kept for column parity.
      fle_status: null,
      fle_encrypted_fields: null,
      c_port: null,
      // Not separable from time_taken at the edge.
      time_to_first_byte: null,
      x_edge_detailed_result_type: cacheStatus,
      sc_content_type: res?.headers.get("content-type") ?? null,
      sc_content_len: res?.headers.get("content-length") ?? null,
      sc_range_start: contentRange?.start ?? null,
      sc_range_end: contentRange?.end ?? null,

      // Beyond CloudFront -- things Cloudflare hands us for nothing. Kept in a
      // separate block so the parity set above stays recognisable.
      cf_country: cf?.country ?? null,
      cf_continent: cf?.continent ?? null,
      cf_asn: cf?.asn ?? null,
      cf_as_organization: cf?.asOrganization ?? null,
      cf_client_tcp_rtt: cf?.clientTcpRtt ?? null,
      cf_client_accept_encoding: cf?.clientAcceptEncoding ?? null,

      // And then the whole thing, verbatim.
      //
      // We get one shot at this: a field not written here is not recoverable
      // later, and enumerating what we think Cloudflare exposes guarantees we
      // miss whatever it adds next. So do not enumerate -- keep the object.
      // Costs a few hundred bytes per request and removes the entire class of
      // "we should have logged that".
      //
      // Named fields above are kept anyway: they are the calibration surface
      // against CloudFront and should not move if Cloudflare renames something
      // in here. This is deliberate duplication.
      //
      // Only Cloudflare's own inferences about the connection go in. Request
      // headers do not: those carry user-supplied secrets (cookies,
      // authorization) that have no business in a permanent archive.
      //
      // Minus three per-connection fields, dropped by name so anything new
      // still lands. They were ~32% of every record and group nothing: the
      // exported authenticator and client random are unique per connection,
      // and tlsClientAuth is empty because the site never asks for a client
      // certificate (bioc-edge#30).
      cf: cf ? logCf(cf as unknown as Record<string, unknown>) : null,
  };
}
