(* Copyright (c) 2016-present, Facebook, Inc.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree. *)

open Core
open Ast
open Analysis
open Pyre
open PostprocessSharedMemory

let register_ignores ~configuration scheduler sources =
  let handles = List.map sources ~f:(fun { Source.relative; _ } -> relative) in
  (* Invalidate keys before updating *)
  let remove_ignores handles =
    List.filter_map ~f:IgnoreKeys.get handles
    |> List.concat
    |> IgnoreLines.KeySet.of_list
    |> IgnoreLines.remove_batch;
    handles |> IgnoreKeys.KeySet.of_list |> IgnoreKeys.remove_batch
  in
  let timer = Timer.start () in
  remove_ignores handles;

  (* Register new values *)
  let register_ignore { Source.relative; metadata = { Source.Metadata.ignore_lines; _ }; _ } =
    (* Register new ignores. *)
    let ignore_map =
      let add_ignore ignore_map ignore_line =
        Location.Reference.Map.add_multi ~key:(Ignore.key ignore_line) ~data:ignore_line ignore_map
      in
      List.fold ~init:Location.Reference.Map.empty ~f:add_ignore ignore_lines
    in
    Map.iteri ~f:(fun ~key ~data -> IgnoreLines.add key data) ignore_map;
    IgnoreKeys.add relative (List.map ~f:Ignore.key ignore_lines)
  in
  let register source_paths = List.iter source_paths ~f:register_ignore in
  Scheduler.iter scheduler ~configuration ~f:register ~inputs:sources;
  Statistics.performance ~name:"registered ignores" ~timer ()


let ignore ~configuration scheduler sources errors =
  let error_lookup =
    let add_to_lookup lookup error =
      Map.add_multi ~key:(Error.key error) ~data:(Error.code error) lookup
    in
    List.fold errors ~init:Location.Reference.Map.empty ~f:add_to_lookup
  in
  let errors =
    let not_ignored error =
      let get_codes = List.concat_map ~f:Ignore.codes in
      IgnoreLines.get (Error.key error)
      >>| (fun ignores ->
            not
              ( List.is_empty (get_codes ignores)
              || List.mem ~equal:( = ) (get_codes ignores) (Error.code error) ))
      |> Option.value ~default:true
    in
    List.filter ~f:not_ignored errors
  in
  let unused_ignores =
    let get_unused_ignores { Source.relative; _ } =
      let ignores =
        let key_to_ignores sofar key =
          IgnoreLines.get key >>| (fun ignores -> ignores @ sofar) |> Option.value ~default:sofar
        in
        List.fold (IgnoreKeys.get relative |> Option.value ~default:[]) ~init:[] ~f:key_to_ignores
      in
      let ignores = List.dedup_and_sort ~compare:Ignore.compare ignores in
      let filter_active_ignores sofar ignore =
        match Ignore.kind ignore with
        | Ignore.TypeIgnore -> sofar
        | _ -> (
          match Map.find error_lookup (Ignore.key ignore) with
          | Some codes ->
              let unused_codes =
                let find_unused sofar code =
                  if List.mem ~equal:( = ) codes code then sofar else code :: sofar
                in
                List.fold ~init:[] ~f:find_unused (Ignore.codes ignore)
              in
              if List.is_empty (Ignore.codes ignore) || List.is_empty unused_codes then
                sofar
              else
                { ignore with Ignore.codes = unused_codes } :: sofar
          | _ -> ignore :: sofar )
      in
      List.fold ~init:[] ~f:filter_active_ignores ignores
    in
    let map _ = List.concat_map ~f:get_unused_ignores in
    Scheduler.map_reduce
      scheduler
      ~configuration
      ~map
      ~reduce:List.append
      ~initial:[]
      ~inputs:sources
      ()
  in
  let create_unused_ignore_error errors unused_ignore =
    let error =
      {
        Error.location = Ignore.location unused_ignore;
        kind = Error.UnusedIgnore (Ignore.codes unused_ignore);
        signature =
          {
            Node.location = Ignore.location unused_ignore;
            value = Statement.Define.Signature.create_toplevel ~qualifier:None;
          };
      }
    in
    error :: errors
  in
  List.fold ~init:errors ~f:create_unused_ignore_error unused_ignores


let shared_memory_hash_to_key_map module_tracker =
  let keys =
    Analysis.ModuleTracker.all_source_paths module_tracker
    |> List.map ~f:(fun { Ast.SourcePath.relative; _ } -> relative)
  in
  let extend_map map ~new_map =
    Map.merge_skewed map new_map ~combine:(fun ~key:_ value _ -> value)
  in
  let all_locations = List.filter_map keys ~f:IgnoreKeys.get |> List.concat in
  IgnoreKeys.compute_hashes_to_keys ~keys
  |> extend_map ~new_map:(IgnoreLines.compute_hashes_to_keys ~keys:all_locations)


let serialize_decoded decoded =
  match decoded with
  | IgnoreLines.Decoded (key, value) ->
      Some (IgnoreValue.description, key, Option.map value ~f:(List.to_string ~f:Ast.Ignore.show))
  | IgnoreKeys.Decoded (key, value) ->
      Some
        (LocationListValue.description, key, Option.map value ~f:(List.to_string ~f:Location.show))
  | _ -> None


let decoded_equal first second =
  match first, second with
  | IgnoreLines.Decoded (_, first), IgnoreLines.Decoded (_, second) ->
      Some (Option.equal IgnoreValue.equal first second)
  | IgnoreKeys.Decoded (_, first), IgnoreKeys.Decoded (_, second) ->
      Some (Option.equal LocationListValue.equal first second)
  | _ -> None
