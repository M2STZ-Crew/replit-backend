import OrgDirectory from './OrgDirectory.jsx';

// The Affiliates section is the directory of accepted partner organizations
// (rosters + equipment). Onboarding-request review lives under Accounts.
export default function AffiliatesPanel({ query, onQuery }) {
  return <OrgDirectory query={query} onQuery={onQuery} />;
}
