import {
  BarChart,
  Button,
  Callout,
  Card,
  CardBody,
  CardHeader,
  Divider,
  Grid,
  H1,
  H2,
  H3,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
  UsageBar,
  useCanvasState,
  useHostTheme,
} from "cursor/canvas";
import type { ReactNode } from "react";

type ConceptId = "current" | "briefing" | "hours" | "triage" | "hybrid";

const CONCEPTS: { id: ConceptId; label: string; tagline: string }[] = [
  { id: "current", label: "Today", tagline: "HTML dump in QTextBrowser" },
  {
    id: "briefing",
    label: "A · Sprint briefing",
    tagline: "KPI hero + section tabs",
  },
  {
    id: "hours",
    label: "B · Hours explorer",
    tagline: "Matrix-first for daily logs",
  },
  {
    id: "triage",
    label: "C · Attention triage",
    tagline: "Risks & hygiene first",
  },
  {
    id: "hybrid",
    label: "D · Hybrid (recommended)",
    tagline: "Native shell + export intact",
  },
];

const HOURS_BY_DAY = [
  { label: "May 27", stories: 32, tasks: 0 },
  { label: "May 28", stories: 40, tasks: 0 },
  { label: "May 29", stories: 36, tasks: 0 },
  { label: "Jun 01", stories: 40, tasks: 0 },
  { label: "Jun 02", stories: 40, tasks: 0 },
  { label: "Jun 03", stories: 26, tasks: 6 },
  { label: "Jun 04", stories: 46, tasks: 2 },
  { label: "Jun 05", stories: 46, tasks: 0 },
  { label: "Jun 08", stories: 30, tasks: 2 },
  { label: "Jun 09", stories: 52, tasks: 0 },
];

export default function ReportPageRedesign() {
  const [concept, setConcept] = useCanvasState<ConceptId>("concept", "hybrid");

  return (
    <Stack gap={24}>
      <Stack gap={8}>
        <H1>Sprint report page — redesign options</H1>
        <Text tone="secondary">
          Grounded in sample output Wi-Fi_LMAC_2026_11 and the current Generate
          page (QTextBrowser HTML preview). Goal: stop treating the export file
          as the UI — keep MD/HTML for sharing, rebuild the in-app page as a
          native review surface.
        </Text>
      </Stack>

      <Callout tone="warning" title="Why the current page feels limited">
        The Generate page loads the exported HTML into QTextBrowser. Wide hours
        tables scroll poorly, theme JS is stripped, MD fallback is raw text, and
        there is no filter / sort / drill-down. The report already has rich
        structure (KPIs, hours, validation, tickets) — the UI does not use it.
      </Callout>

      <Grid columns={5} gap={12}>
        <Stat value="83%" label="Completion (tickets)" tone="warning" />
        <Stat value="87%" label="Completion (SP)" tone="warning" />
        <Stat value="0.70" label="Velocity SP/day" />
        <Stat value="388h" label="Story hours logged" />
        <Stat value="3" label="Attention items" tone="danger" />
      </Grid>

      <Stack gap={10}>
        <H2>Pick a concept</H2>
        <Row gap={8} wrap>
          <Pill active={concept === "current"} onClick={() => setConcept("current")}>
            Today
          </Pill>
          <Pill active={concept === "briefing"} onClick={() => setConcept("briefing")}>
            A · Sprint briefing
          </Pill>
          <Pill active={concept === "hours"} onClick={() => setConcept("hours")}>
            B · Hours explorer
          </Pill>
          <Pill active={concept === "triage"} onClick={() => setConcept("triage")}>
            C · Attention triage
          </Pill>
          <Pill active={concept === "hybrid"} onClick={() => setConcept("hybrid")}>
            D · Hybrid (recommended)
          </Pill>
        </Row>
        <Text tone="secondary" size="small">
          {CONCEPTS.find((c) => c.id === concept)?.tagline}
        </Text>
      </Stack>

      <Divider />

      {concept === "current" && <CurrentMock />}
      {concept === "briefing" && <BriefingMock />}
      {concept === "hours" && <HoursMock />}
      {concept === "triage" && <TriageMock />}
      {concept === "hybrid" && <HybridMock />}

      <Divider />

      <Stack gap={12}>
        <H2>Side-by-side comparison</H2>
        <Table
          headers={[
            "Aspect",
            "Today",
            "A Briefing",
            "B Hours",
            "C Triage",
            "D Hybrid",
          ]}
          rows={[
            [
              "Primary job",
              "Read export",
              "Sprint health at a glance",
              "Who logged what",
              "Fix risks first",
              "Review + export",
            ],
            [
              "Hours tables",
              "Cramped HTML",
              "Behind a tab",
              "Hero matrix",
              "Secondary",
              "Dedicated Hours tab",
            ],
            [
              "Validation / churn",
              "Buried mid-doc",
              "KPI strip only",
              "Easy to miss",
              "Top queue",
              "Overview + Alerts tab",
            ],
            [
              "Tickets list",
              "Long scroll",
              "Filterable table",
              "Secondary",
              "Open / warn first",
              "Filterable Tickets tab",
            ],
            [
              "Chart",
              "PNG at bottom",
              "Overview panel",
              "Beside matrix",
              "Optional",
              "Overview + Hours",
            ],
            [
              "MD/HTML export",
              "Is the UI",
              "Still written",
              "Still written",
              "Still written",
              "Buttons: Open / Reveal",
            ],
            [
              "Qt fit",
              "QTextBrowser",
              "Native widgets",
              "Native + heatmap",
              "Native cards",
              "Native tabs + QTable",
            ],
            [
              "Build effort",
              "—",
              "Medium",
              "High",
              "Medium",
              "Medium–high",
            ],
          ]}
        />
      </Stack>

      <Stack gap={12}>
        <H2>Recommendation</H2>
        <Card>
          <CardHeader trailing={<Pill size="sm">Best ROI</Pill>}>
            Ship concept D (Hybrid)
          </CardHeader>
          <CardBody>
            <Stack gap={10}>
              <Text>
                Keep writing MD + HTML for email / Confluence / archive. Rebuild
                the Generate page as a native Overview · Hours · Alerts ·
                Tickets · Chart shell fed by structured report data (not by
                re-parsing the HTML). That matches how managers actually read
                the report, and avoids QTextBrowser layout limits.
              </Text>
              <UsageBar
                total={100}
                topLeftLabel="UI weight by tab"
                topRightLabel="equal review focus"
                segments={[
                  { id: "overview", value: 25 },
                  { id: "hours", value: 30 },
                  { id: "alerts", value: 20 },
                  { id: "tickets", value: 25 },
                ]}
              />
              <Text tone="secondary" size="small">
                Suggested first slice: Overview KPI strip + Alerts list +
                Tickets QTableView, with Hours still opening the HTML section
                until the matrix lands.
              </Text>
            </Stack>
          </CardBody>
        </Card>
      </Stack>

      <Text tone="tertiary" size="small">
        Source: output/sprint_report_Wi-Fi_LMAC_2026_11.md · completion 83% / SP
        87% · velocity 0.70 · 3 open tickets · 2 hygiene warnings · 1 mid-sprint
        add · 2 sub-task worklogs.
      </Text>
    </Stack>
  );
}

function SectionChrome({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <Stack gap={14}>
      <Stack gap={4}>
        <H2>{title}</H2>
        <Text tone="secondary">{subtitle}</Text>
      </Stack>
      <Card>
        <CardHeader
          trailing={
            <Row gap={6}>
              <Pill size="sm">MD</Pill>
              <Pill size="sm" active>
                HTML
              </Pill>
            </Row>
          }
        >
          Generate · Wi-Fi_LMAC_2026_11
        </CardHeader>
        <CardBody>
          <Stack gap={12}>
            <Text tone="secondary" size="small">
              May 27 – Jun 09, 2026 · Report date: today
            </Text>
            {children}
          </Stack>
        </CardBody>
      </Card>
    </Stack>
  );
}

function CurrentMock() {
  return (
    <SectionChrome
      title="Today — document preview"
      subtitle="One long HTML/MD scroll. No navigation between sections."
    >
      <Stack gap={12}>
        <Text weight="semibold">Sprint Report: Wi-Fi_LMAC_2026_11</Text>
        <Text tone="secondary" size="small">
          Sprint Duration: May 27, 2026 – Jun 09, 2026 (2 weeks) …
        </Text>
        <Text size="small" tone="tertiary">
          [wide markdown table: Person × 10 weekday columns with nested ticket
          lines — horizontal scroll, hard to scan]
        </Text>
        <Divider />
        <Text size="small" tone="tertiary">
          … KPI table with many N/A rows … validation mid-page … tickets …
          chart only if you scroll to the end …
        </Text>
        <Callout tone="neutral" title="Pain">
          Same content as the file. Managers cannot jump to “what’s wrong” or
          “who logged hours” without hunting through the document.
        </Callout>
      </Stack>
    </SectionChrome>
  );
}

function BriefingMock() {
  return (
    <SectionChrome
      title="A — Sprint briefing"
      subtitle="Lead with health metrics; deep tables live behind tabs."
    >
      <Stack gap={16}>
        <Grid columns={4} gap={12}>
          <Stat value="83%" label="Ticket completion" tone="warning" />
          <Stat value="87%" label="SP completion" tone="warning" />
          <Stat value="0.70" label="Velocity" />
          <Stat value="1" label="Scope churn" tone="warning" />
        </Grid>
        <Row gap={8} wrap>
          <Pill active>Overview</Pill>
          <Pill>Hours</Pill>
          <Pill>Validation</Pill>
          <Pill>Tickets</Pill>
        </Row>
        <Grid columns="1.2fr 1fr" gap={16}>
          <Stack gap={8}>
            <H3>Team completion</H3>
            <Table
              headers={["Metric", "Value", "Target"]}
              columnAlign={["left", "right", "left"]}
              rows={[
                ["Tickets done", "15 / 18", "—"],
                ["SP delivered", "33 / 38", "—"],
                ["Completion (tickets)", "83%", "≥ 90%"],
                ["Velocity", "0.70 SP/day", "—"],
              ]}
              rowTone={[undefined, undefined, "warning", undefined]}
            />
          </Stack>
          <Stack gap={8}>
            <H3>Hours trend (stories vs tasks)</H3>
            <BarChart
              categories={HOURS_BY_DAY.map((d) => d.label)}
              series={[
                {
                  name: "Stories (h)",
                  data: HOURS_BY_DAY.map((d) => d.stories),
                },
                {
                  name: "Tasks (h)",
                  data: HOURS_BY_DAY.map((d) => d.tasks),
                },
              ]}
              height={180}
            />
            <Text tone="tertiary" size="small">
              Source: sample report team totals · weekday columns
            </Text>
          </Stack>
        </Grid>
        <Callout tone="info" title="Strength">
          Matches end-of-sprint review: status first, evidence second. Weak
          spot: hours matrix still needs a strong Hours tab or it stays
          second-class.
        </Callout>
      </Stack>
    </SectionChrome>
  );
}

function HoursMock() {
  return (
    <SectionChrome
      title="B — Hours explorer"
      subtitle="Make the two giant tables usable: Stories / Tasks toggle, person filter, cell drill-down."
    >
      <Stack gap={14}>
        <Row gap={8} align="center" justify="space-between" wrap>
          <Row gap={8}>
            <Pill active>Stories · 388h</Pill>
            <Pill>Tasks · 10h</Pill>
          </Row>
          <Text tone="secondary" size="small">
            Filter person · expand cell for ticket keys
          </Text>
        </Row>
        <Table
          headers={[
            "Person",
            "May 27",
            "May 28",
            "May 29",
            "Jun 01",
            "Jun 02",
            "Total",
          ]}
          columnAlign={[
            "left",
            "right",
            "right",
            "right",
            "right",
            "right",
            "right",
          ]}
          rows={[
            ["Sunil Jangiti", "4.0", "8.0", "8.0", "8.0", "8.0", "60.0"],
            ["Hemanth Reddy Narra", "8.0", "8.0", "8.0", "8.0", "8.0", "72.0"],
            ["Shivam Patil", "8.0", "8.0", "8.0", "8.0", "8.0", "80.0"],
            ["Kiran Bikkanoori", "4.0", "8.0", "8.0", "8.0", "8.0", "72.0"],
            ["Ashwini Kumar", "8.0", "8.0", "4.0", "8.0", "8.0", "72.0"],
            ["Ritesh Seemakurty", "0.0", "0.0", "0.0", "0.0", "0.0", "32.0"],
            ["Team total", "32.0", "40.0", "36.0", "40.0", "40.0", "388.1"],
          ]}
          rowTone={[
            undefined,
            undefined,
            undefined,
            undefined,
            undefined,
            "warning",
            "info",
          ]}
        />
        <Text tone="secondary" size="small">
          Clicking 8.0 under May 28 / Sunil would open a side panel: RSCDEV-47833
          6.0h · RSCDEV-47913 2.0h — instead of cramming keys into every cell.
        </Text>
        <Callout tone="info" title="Strength">
          Solves the worst part of the current preview. Pair with a thin KPI
          header so completion/velocity are not buried.
        </Callout>
      </Stack>
    </SectionChrome>
  );
}

function TriageMock() {
  return (
    <SectionChrome
      title="C — Attention triage"
      subtitle="Surface unfinished work, hygiene flags, churn, and sub-task logging before the rest."
    >
      <Stack gap={14}>
        <Grid columns={3} gap={12}>
          <Stat value="3" label="Not done" tone="danger" />
          <Stat value="2" label="Done w/ remaining" tone="warning" />
          <Stat value="2" label="Sub-task worklogs" tone="warning" />
        </Grid>
        <H3>Attention queue</H3>
        <Table
          headers={["Severity", "Item", "Why it matters"]}
          rows={[
            [
              "High",
              "SI91X-21524 · Blocked · 6h remaining",
              "Open task + mid-sprint add",
            ],
            [
              "High",
              "RSCDEV-47824 · In Progress · 8h left",
              "Sprint activities still open",
            ],
            [
              "High",
              "RSCDEV-47828 · Open · 16h left",
              "Unstarted committed story",
            ],
            [
              "Med",
              "RSCDEV-43109 Closed but 32h remaining",
              "Jira hygiene / estimate cleanup",
            ],
            [
              "Med",
              "RSCDEV-46403 Closed but 23h remaining",
              "Jira hygiene / estimate cleanup",
            ],
            [
              "Low",
              "2 worklogs on sub-tasks",
              "Should usually land on story/task",
            ],
          ]}
          rowTone={[
            "danger",
            "danger",
            "danger",
            "warning",
            "warning",
            undefined,
          ]}
        />
        <Callout tone="info" title="Strength">
          Perfect for mid-sprint or SM review. Weak alone for hour audits —
          needs Hours as a peer view.
        </Callout>
      </Stack>
    </SectionChrome>
  );
}

function HybridMock() {
  const theme = useHostTheme();
  return (
    <SectionChrome
      title="D — Hybrid (recommended)"
      subtitle="Native review shell with five destinations. Export files stay the shareable artifact."
    >
      <Stack gap={16}>
        <Row gap={8} justify="space-between" wrap>
          <Row gap={8} wrap>
            <Pill active>Overview</Pill>
            <Pill>Hours</Pill>
            <Pill active={false}>Alerts · 5</Pill>
            <Pill>Tickets</Pill>
            <Pill>Chart</Pill>
          </Row>
          <Row gap={8}>
            <Button variant="secondary">Open HTML</Button>
            <Button variant="secondary">Reveal folder</Button>
          </Row>
        </Row>

        <Grid columns={4} gap={12}>
          <Stat value="83%" label="Ticket completion" tone="warning" />
          <Stat value="87%" label="SP completion" tone="warning" />
          <Stat value="0.70" label="Velocity" />
          <Stat value="398h" label="Hours logged" />
        </Grid>

        <Grid columns="1fr 1fr" gap={16}>
          <Card>
            <CardHeader trailing={<Pill size="sm">5</Pill>}>
              Needs attention
            </CardHeader>
            <CardBody>
              <Stack gap={8}>
                <Text size="small">3 unfinished · 2 hygiene · 1 churn</Text>
                <Table
                  headers={["Ticket", "Status"]}
                  rows={[
                    ["SI91X-21524", "Blocked"],
                    ["RSCDEV-47824", "In Progress"],
                    ["RSCDEV-47828", "Open"],
                  ]}
                  rowTone={["danger", "warning", "warning"]}
                />
                <Button variant="ghost">Open Alerts tab</Button>
              </Stack>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>Per-person SP %</CardHeader>
            <CardBody>
              <BarChart
                categories={[
                  "Sunil",
                  "Hemanth",
                  "Shivam",
                  "Kiran",
                  "Ashwini",
                  "Ritesh",
                ]}
                series={[
                  {
                    name: "SP completion %",
                    data: [80, 100, 100, 100, 100, 0],
                  },
                ]}
                height={160}
              />
              <Text
                tone="tertiary"
                size="small"
                style={{ color: theme.text.tertiary }}
              >
                Source: Per-person completion table · sample sprint
              </Text>
            </CardBody>
          </Card>
        </Grid>

        <Stack gap={6}>
          <H3>Information architecture</H3>
          <Table
            headers={["Tab", "Shows", "Replaces in MD/HTML"]}
            rows={[
              [
                "Overview",
                "KPI chips, team metrics, mini charts, goal",
                "Header + KPI + Completion",
              ],
              [
                "Hours",
                "Stories/Tasks matrix, cell detail drawer",
                "Logged Hours tables",
              ],
              [
                "Alerts",
                "Churn, sub-task remaining, sub-task worklogs, warn rows",
                "Validation + churn + warn tickets",
              ],
              [
                "Tickets",
                "Sortable/filterable status & remaining",
                "Sprint Tickets table",
              ],
              [
                "Chart",
                "Embedded hours / future burndown",
                "Hours chart PNG",
              ],
            ]}
          />
        </Stack>

        <Callout tone="success" title="Why this wins">
          Same data pipeline as today — only the Generate UI changes. Export
          stays for Confluence/email. Native Qt tables fix the hours/tickets
          readability problem without throwing away the report format.
        </Callout>

        <Text size="small" tone="tertiary">
          Implementation note: expose structured dicts from report_generator
          (already computed) to the GUI instead of round-tripping through HTML.
        </Text>
      </Stack>
    </SectionChrome>
  );
}
