grant select, insert, update on public.leads to authenticated;
grant select on public.olx_adverts to authenticated;
grant select on public.radar_settings to authenticated;
grant usage, select on sequence public.leads_id_seq to authenticated;

drop policy if exists "radar_leads_select" on public.leads;
create policy "radar_leads_select" on public.leads for select to authenticated using (true);
drop policy if exists "radar_leads_insert" on public.leads;
create policy "radar_leads_insert" on public.leads for insert to authenticated with check (true);
drop policy if exists "radar_leads_update" on public.leads;
create policy "radar_leads_update" on public.leads for update to authenticated using (true) with check (true);
drop policy if exists "radar_olx_select" on public.olx_adverts;
create policy "radar_olx_select" on public.olx_adverts for select to authenticated using (true);
drop policy if exists "radar_settings_select" on public.radar_settings;
create policy "radar_settings_select" on public.radar_settings for select to authenticated using (true);
