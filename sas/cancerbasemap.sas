/******************************************************************************
 NOT YET RUN IN SAS

 Everything DuckDB-side in this file was executed against the live catalog
 (icegate-canceronice.seandavi.workers.dev) with the `duckdb` CLI on a Linux
 build host that has no SAS installed. The SAS statements below (FILENAME
 PIPE, PROC IMPORT, the data step) were written against SAS 9.4 documentation
 for FILENAME PIPE, PROC IMPORT GUESSINGROWS, and INFORMAT/INPUT, but never
 executed by SAS itself.

 If you can run this, please report back on GitHub issue #115
 (seandavi/cancer-basemap) with:
   [ ] SAS 9.4 on Windows  -- does %cancerbasemap() run as written?
   [ ] SAS 9.4 on Linux    -- same, and does the `duckdb` path need changes?
   [ ] SAS Viya            -- does PROC IMPORT still apply, or did you use
                              the Parquet LIBNAME engine / PROC PYTHON instead?
   [ ] XCMD on or off      -- does your site allow FILENAME PIPE at all?
                              (NOXCMD is the default on many managed SAS
                              servers and on SAS OnDemand for Academics/Viya)
   [ ] Leading zeros       -- do county/state FIPS codes inside geo_id survive
                              PROC IMPORT's column-type guessing intact?
   [ ] Missing values      -- does a suppressed cell (empty CSV field) arrive
                              as a genuine SAS numeric missing (.), with
                              value_status still readable?
   [ ] Long strings        -- does attributes_json / address truncate under
                              PROC IMPORT's guessed character length?
   [ ] Windows quoting     -- the `-nullvalue ''` empty-string argument below
                              is POSIX shell syntax (Linux/Unix SAS). FILENAME
                              PIPE on Windows SAS runs through cmd.exe, which
                              does not treat '' as an empty argument the same
                              way; this was never tested on Windows and the
                              quoting likely needs to change there.
******************************************************************************/

/* cancerbasemap: run a read-only SQL query against the Cancer Basemap
   (coi.* in the query text) and land the result in a SAS dataset.

   Route 1 from issue #115: DuckDB does the Iceberg reading; SAS never talks
   to Iceberg or to the network. The DuckDB CLI writes CSV to its stdout,
   FILENAME PIPE reads that stream as a fileref, and PROC IMPORT turns it
   into a dataset.

   Requires:
     - the `duckdb` CLI on the SAS server's PATH (or pass duckdb=/full/path)
     - XCMD enabled for this SAS session (FILENAME PIPE shells out). If your
       site runs with NOXCMD (common on managed SAS 9.4 servers and on SAS
       OnDemand for Academics / Viya), this macro cannot run at all -- see
       "If XCMD is off" below.

   Usage:
     %cancerbasemap(
       query=SELECT geo_id, value, value_status
             FROM coi.measure.observation
             WHERE source = 'PLACES' AND measure_id = 'PLACES:MAMMOUSE:age_adjusted'
               AND source_release = '2025' AND valid_to IS NULL;,
       out=work.mammo
     );
*/
%macro cancerbasemap(query=,
                      out=,
                      duckdb=duckdb,
                      endpoint=https://icegate-canceronice.seandavi.workers.dev,
                      guessingrows=32767);

  filename clqry temp;
  filename clcsv pipe "&duckdb -csv -nullvalue '' -f %sysfunc(pathname(clqry))";

  /* Write the ATTACH boilerplate plus the caller's query to a temp SQL file.
     An ATTACH is per-connection, not stored anywhere -- it has to be issued
     every time the CLI starts, which is why this macro always writes it. */
  data _null_;
    file clqry;
    put "INSTALL iceberg; LOAD iceberg;";
    put "ATTACH 'canceronice' AS coi (TYPE ICEBERG, URI '&endpoint', AUTHORIZATION_TYPE 'none');";
    put "&query";
  run;

  /* Quick path: let PROC IMPORT guess types. Fine when the query's only
     character columns are things like geo_id ('county:08031') that can
     never look like a number. If you SELECT a bare `fips` column instead,
     use the data-step path below -- PROC IMPORT will read "08031" as the
     number 8031 and the leading zero is gone for good. */
  proc import datafile=clcsv out=&out dbms=csv replace;
    guessingrows=&guessingrows;
    getnames=yes;
  run;

  filename clqry clear;
  filename clcsv clear;
%mend cancerbasemap;

/* cancerbasemap_fips: same as above, but for queries that select a bare
   FIPS-shaped character column (e.g. geography.unit.fips) where leading
   zeros matter and must not be left to PROC IMPORT's guessing. Reads the
   pipe with an explicit INFORMAT/INPUT instead. Columns and their SAS types
   must be listed by the caller (VARS=) because a data step INPUT statement,
   unlike PROC IMPORT, cannot discover them from the CSV header.

   Usage:
     %cancerbasemap_fips(
       query=SELECT fips, name FROM coi.geography.unit
             WHERE level='county' AND vintage=2020 AND valid_to IS NULL;,
       out=work.counties,
       vars=fips $5. name $100.
     );
*/
%macro cancerbasemap_fips(query=, out=, vars=,
                           duckdb=duckdb,
                           endpoint=https://icegate-canceronice.seandavi.workers.dev);

  filename clqry temp;
  filename clcsv pipe "&duckdb -csv -nullvalue '' -f %sysfunc(pathname(clqry))";

  data _null_;
    file clqry;
    put "INSTALL iceberg; LOAD iceberg;";
    put "ATTACH 'canceronice' AS coi (TYPE ICEBERG, URI '&endpoint', AUTHORIZATION_TYPE 'none');";
    put "&query";
  run;

  data &out;
    infile clcsv dsd firstobs=2 truncover;
    informat &vars;
    input &vars;
  run;

  filename clqry clear;
  filename clcsv clear;
%mend cancerbasemap_fips;

/******************************************************************************
 If XCMD is off

 FILENAME PIPE (and X, and SYSTASK) all shell out, and NOXCMD blocks all of
 them -- there is no SAS-side workaround. Two options:

 1. Run the `duckdb` CLI on your own machine (or wherever XCMD is allowed) to
    produce the extract, then move the file to where SAS can read it:

      duckdb -csv -nullvalue '' -c "
        INSTALL iceberg; LOAD iceberg;
        ATTACH 'canceronice' AS coi (TYPE ICEBERG,
          URI 'https://icegate-canceronice.seandavi.workers.dev', AUTHORIZATION_TYPE 'none');
        COPY (SELECT ...) TO 'extract.csv' (FORMAT CSV, HEADER TRUE);
      " > extract.csv

    then upload extract.csv and PROC IMPORT it directly -- no PIPE, no XCMD.

 2. On Viya: use `COPY (...) TO 'extract.parquet' (FORMAT PARQUET)` instead
    and read it with Viya's Parquet LIBNAME engine (CAS or SAS/ACCESS
    Interface to Parquet) once uploaded -- again no shelling out from SAS.

 Both are the same DuckDB-side step documented and run in docs/CLIENTS.md;
 only where the CLI runs (SAS host vs. your laptop) changes.
******************************************************************************/
